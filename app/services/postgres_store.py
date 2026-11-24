"""Short transactional session/document/message operations; no filesystem cleanup."""
import hashlib
from hmac import compare_digest
import os
import time
import math
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from sqlalchemy import select, insert, update, delete, func
from app.db.runtime import get_engine, verify_schema, dispose_engine
from app.db.schema import sessions, messages, documents, chunks, request_leases, owner_credentials
from app.services.session_credentials import OWNER_LIFETIME_SECONDS, SESSION_ID, OwnerCredential
from utils.embeddings import PROFILE_ID, validate_vectors
from utils.memory_limits import HistoryWindow, load_memory_limits

SESSION_TTL_SECONDS = int(os.getenv('SESSION_TTL_SECONDS', '86400'))
SESSION_CLEANUP_INTERVAL_SECONDS = int(os.getenv('SESSION_CLEANUP_INTERVAL_SECONDS', '3600'))


def retention_enabled():
    # Historical import retention remains off until explicitly enabled.
    return os.getenv('SESSION_RETENTION_ENABLED', 'false').lower() == 'true'


def timestamp(value=None):
    return datetime.fromtimestamp(int(time.time() if value is None else value), timezone.utc)


def init_session_store():
    if SESSION_TTL_SECONDS <= 0 or SESSION_CLEANUP_INTERVAL_SECONDS <= 0:
        raise ValueError('Session lifecycle settings must be positive.')
    verify_schema()


def create_session() -> str:
    """Create an internal session without public access (offline tooling)."""
    return _create_session()[0]


def create_owned_session(owner: OwnerCredential) -> tuple[str, datetime]:
    return _create_session(owner)


def _create_session(owner: OwnerCredential | None = None) -> tuple[str, datetime]:
    sid = uuid4().hex
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=OWNER_LIFETIME_SECONDS)
    with get_engine().begin() as connection:
        activity_at = timestamp()
        connection.execute(insert(sessions).values(session_id=sid, created_at=activity_at, updated_at=activity_at))
        if owner is not None:
            connection.execute(insert(owner_credentials).values(
                session_id=sid, digest=owner.digest, mode=owner.mode,
                issued_at=now, expires_at=expires_at,
            ))
    return sid, expires_at


def _owner_is_valid(connection, sid: str, owner: OwnerCredential) -> bool:
    row = connection.execute(select(
        owner_credentials.c.digest, owner_credentials.c.mode, owner_credentials.c.expires_at,
    ).where(owner_credentials.c.session_id == sid)).first()
    return bool(row and compare_digest(row.digest, owner.digest)
                and row.mode == owner.mode and datetime.now(timezone.utc) < row.expires_at)


def check_session_owner(sid: str, owner: OwnerCredential) -> bool:
    """Read only credential metadata before accepting a request body."""
    with get_engine().connect() as connection:
        if not _owner_is_valid(connection, sid, owner):
            return False
        if not retention_enabled():
            return True
        updated_at = connection.scalar(select(sessions.c.updated_at).where(sessions.c.session_id == sid))
        now = timestamp()
        return updated_at is not None and (
            updated_at > now - timedelta(seconds=SESSION_TTL_SECONDS) or _has_lease(connection, sid, now)
        )


def _has_lease(connection, sid, now):
    return connection.scalar(select(request_leases.c.lease_id).where(
        request_leases.c.session_id == sid, request_leases.c.expires_at > now).limit(1)) is not None


def _locked_session(connection, sid, now=None):
    row = connection.execute(select(sessions).where(sessions.c.session_id == sid).with_for_update()).mappings().first()
    if row is None:
        raise LookupError('Session not found.')
    # Capture wall time only after the row lock. Never move activity backwards
    # when a worker was queued or the system clock was adjusted.
    now = timestamp()
    if retention_enabled() and row['updated_at'].timestamp() <= now.timestamp() - SESSION_TTL_SECONDS and not _has_lease(connection, sid, now):
        raise LookupError('Session expired.')
    return row


def acquire_session_lease(sid: str, duration_seconds: float):
    if not math.isfinite(duration_seconds) or duration_seconds <= 0:
        raise ValueError('Request lease requires a finite positive remaining deadline.')
    lease_id = uuid4()
    started = time.monotonic()
    with get_engine().begin() as connection:
        row = _locked_session(connection, sid)
        remaining = duration_seconds - (time.monotonic() - started)
        if remaining <= 0:
            raise TimeoutError('Request lease deadline expired while waiting for the database.')
        now = max(row['updated_at'], timestamp())
        connection.execute(update(sessions).where(sessions.c.session_id == sid).values(updated_at=now))
        connection.execute(insert(request_leases).values(lease_id=lease_id, session_id=sid,
            expires_at=timestamp() + timedelta(seconds=remaining)))
    return lease_id


def release_session_lease(sid: str, lease_id) -> None:
    with get_engine().begin() as connection:
        # Release still works after cancellation/deadline; server SQL timeouts
        # remain enabled. No LLM or data write is retried if cleanup fails.
        connection = connection.execution_options(skip_request_budget=True)
        row = connection.execute(select(sessions).where(sessions.c.session_id == sid).with_for_update()).mappings().first()
        if row is not None:
            connection.execute(update(sessions).where(sessions.c.session_id == sid).values(
                updated_at=max(row['updated_at'], timestamp())))
        connection.execute(delete(request_leases).where(request_leases.c.lease_id == lease_id,
                                                         request_leases.c.session_id == sid))


def get_session(sid, *, owner: OwnerCredential | None = None):
    if not isinstance(sid, str) or not SESSION_ID.fullmatch(sid):
        return None
    limit = load_memory_limits().history_messages
    expired = False
    with get_engine().begin() as connection:
        row = connection.execute(select(sessions).where(sessions.c.session_id == sid).with_for_update()).mappings().first()
        if row is None or (owner is not None and not _owner_is_valid(connection, sid, owner)):
            return None
        now = timestamp()
        if retention_enabled() and row['updated_at'].timestamp() <= now.timestamp() - SESSION_TTL_SECONDS and not _has_lease(connection, sid, now):
            if owner is not None:
                return None
            connection.execute(delete(sessions).where(sessions.c.session_id == sid))
            expired = True
        else:
            now = max(row['updated_at'], now)
            connection.execute(update(sessions).where(sessions.c.session_id == sid).values(updated_at=now))
            total = connection.scalar(select(func.count()).select_from(messages).where(messages.c.session_id == sid))
            history = list(reversed(connection.execute(select(messages.c.payload).where(
                messages.c.session_id == sid).order_by(messages.c.ordinal.desc()).limit(limit)).scalars().all()))
            names = connection.execute(select(documents.c.filename).where(documents.c.session_id == sid).order_by(documents.c.document_id)).scalars().all()
            has_chunks = connection.scalar(select(chunks.c.chunk_id).where(chunks.c.session_id == sid).limit(1)) is not None
    if expired:
        from utils.memory import invalidate_memory
        invalidate_memory(sid)
        return None
    from utils.pgvector_store import SessionVectorStore
    return dict(session_id=sid, loaded_pdfs=names, messages=HistoryWindow(history, total), message_count=total,
                vectorstore=SessionVectorStore(sid) if has_chunks else None,
                document_count=row['document_count'], created_at=int(row['created_at'].timestamp()),
                updated_at=int(now.timestamp()), _persisted_message_count=len(history), _message_batch_id=uuid4())


def save_session(session):
    """Append this snapshot's new messages, never overwrite concurrent history."""
    sid = session['session_id']
    start = session.get('_persisted_message_count')
    if start is None:
        raise ValueError('A persisted session snapshot is required.')
    batch = session.setdefault('_message_batch_id', uuid4())
    payloads = session['messages'][start:]
    if not payloads:
        return
    with get_engine().begin() as connection:
        row = _locked_session(connection, sid)
        now = max(row['updated_at'], timestamp())
        existing = connection.execute(select(messages.c.payload).where(
            messages.c.session_id == sid, messages.c.batch_id == batch).order_by(messages.c.batch_ordinal)).scalars().all()
        if existing:
            if existing != payloads:
                raise ValueError('Message batch conflicts with previously committed content.')
        else:
            offset = connection.scalar(select(func.coalesce(func.max(messages.c.ordinal), -1)).where(messages.c.session_id == sid)) + 1
            connection.execute(insert(messages), [dict(session_id=sid, ordinal=offset+i, payload=p,
                batch_id=batch, batch_ordinal=i) for i,p in enumerate(payloads)])
        connection.execute(update(sessions).where(sessions.c.session_id == sid).values(updated_at=now))
        total = connection.scalar(select(func.count()).select_from(messages).where(messages.c.session_id == sid))
    session['message_count'] = total
    session['_persisted_message_count'] = len(session['messages'])
    session['_message_batch_id'] = uuid4()
    session['updated_at'] = int(now.timestamp())


def commit_document(sid, filename, page_count, items, vectors, *, size_bytes=None, sha256=None):
    vectors = validate_vectors(vectors, expected_count=len(items)) if items else []
    if not items:
        raise ValueError('PDF contains no searchable text.')
    if any(item.metadata.get('source') != filename for item in items):
        raise ValueError('Chunk source does not match its document.')
    with get_engine().begin() as connection:
        row = _locked_session(connection, sid)
        now = max(row['updated_at'], timestamp())
        if connection.scalar(select(documents.c.document_id).where(documents.c.session_id == sid, documents.c.filename == filename)) is not None:
            return False
        document_id = connection.scalar(select(func.coalesce(func.max(documents.c.document_id), -1)).where(documents.c.session_id == sid)) + 1
        connection.execute(insert(documents).values(session_id=sid, document_id=document_id, filename=filename,
            page_count=page_count, chunk_count=len(items), size_bytes=size_bytes, sha256=sha256, uploaded_at=now))
        connection.execute(insert(chunks), [dict(chunk_id=uuid4(), session_id=sid, document_id=document_id,
            chunk_ordinal=i, content=item.page_content, metadata=dict(item.metadata), embedding=vectors[i],
            embedding_profile_id=PROFILE_ID, content_sha256=hashlib.sha256(item.page_content.encode()).hexdigest())
            for i,item in enumerate(items)])
        connection.execute(update(sessions).where(sessions.c.session_id == sid).values(
            document_count=row['document_count'] + page_count, updated_at=now))
    return True


def delete_session(sid, *, owner: OwnerCredential | None = None) -> bool:
    with get_engine().begin() as connection:
        if owner is not None:
            try:
                _locked_session(connection, sid)
            except LookupError:
                return False
            if not _owner_is_valid(connection, sid, owner):
                return False
        deleted = connection.execute(delete(sessions).where(sessions.c.session_id == sid)).rowcount > 0
    if deleted:
        from utils.memory import invalidate_memory
        invalidate_memory(sid)
    return deleted


def delete_document(sid, filename):
    """Internal operation only; inherited unknown page counts cannot be guessed."""
    with get_engine().begin() as connection:
        row = _locked_session(connection, sid)
        document = connection.execute(select(documents).where(
            documents.c.session_id == sid, documents.c.filename == filename)).mappings().first()
        if document is None:
            return False
        if document['page_count'] is None:
            raise ValueError('Imported document page count is unknown; deletion requires reviewed metadata.')
        connection.execute(delete(documents).where(documents.c.session_id == sid,
            documents.c.document_id == document['document_id']))
        connection.execute(update(sessions).where(sessions.c.session_id == sid).values(
            document_count=row['document_count'] - document['page_count'], updated_at=max(row['updated_at'], timestamp())))
        return True


def cleanup_expired_sessions(now=None):
    reference = timestamp(now)
    cutoff = reference - timedelta(seconds=SESSION_TTL_SECONDS)
    with get_engine().begin() as connection:
        connection.execute(delete(request_leases).where(request_leases.c.expires_at <= reference))
        if not retention_enabled():
            return {'expired_sessions': 0, 'orphaned_vectorstores': 0}
        active = select(request_leases.c.lease_id).where(request_leases.c.session_id == sessions.c.session_id,
            request_leases.c.expires_at > reference).exists()
        removed = connection.execute(delete(sessions).where(sessions.c.updated_at <= cutoff, ~active).returning(sessions.c.session_id)).scalars().all()
    from utils.memory import invalidate_memory
    for sid in removed:
        invalidate_memory(sid)
    return {'expired_sessions': len(removed), 'orphaned_vectorstores': 0}
