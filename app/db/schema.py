"""Relational and dense-vector metadata. Schema is installed only by Alembic."""
from sqlalchemy import (MetaData, Table, Column, String, Text, Integer, BigInteger,
                        DateTime, ForeignKey, ForeignKeyConstraint, CheckConstraint,
                        UniqueConstraint, Index)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from pgvector.sqlalchemy import VECTOR

metadata = MetaData()
sessions = Table('sessions', metadata,
    Column('session_id', String(32), primary_key=True),
    Column('document_count', Integer, nullable=False, server_default='0'),
    Column('created_at', DateTime(timezone=True), nullable=False),
    Column('updated_at', DateTime(timezone=True), nullable=False),
    CheckConstraint("session_id ~ '^[a-f0-9]{32}$'", name='session_id_format'),
    CheckConstraint('document_count >= 0', name='session_pages_nonnegative'),
)
Index('ix_sessions_updated_at', sessions.c.updated_at)
request_leases = Table('session_request_leases', metadata,
    Column('lease_id', UUID(as_uuid=True), primary_key=True),
    Column('session_id', String(32), ForeignKey('sessions.session_id', ondelete='CASCADE'), nullable=False),
    Column('expires_at', DateTime(timezone=True), nullable=False),
)
Index('ix_request_lease_session_expiry', request_leases.c.session_id, request_leases.c.expires_at)
messages = Table('session_messages', metadata,
    Column('session_id', String(32), ForeignKey('sessions.session_id', ondelete='CASCADE'), primary_key=True),
    Column('ordinal', BigInteger, primary_key=True),
    Column('payload', JSONB, nullable=False),
    Column('batch_id', UUID(as_uuid=True), nullable=False),
    Column('batch_ordinal', Integer, nullable=False),
    UniqueConstraint('session_id', 'batch_id', 'batch_ordinal', name='uq_message_batch'),
    CheckConstraint('ordinal >= 0 AND batch_ordinal >= 0', name='message_order_nonnegative'),
    CheckConstraint("jsonb_typeof(payload) = 'object'", name='message_payload_object'),
)
documents = Table('session_documents', metadata,
    Column('session_id', String(32), ForeignKey('sessions.session_id', ondelete='CASCADE'), primary_key=True),
    Column('document_id', Integer, primary_key=True),
    Column('filename', Text, nullable=False),
    Column('page_count', Integer),
    Column('chunk_count', Integer),
    Column('size_bytes', BigInteger),
    Column('sha256', String(64)),
    Column('uploaded_at', DateTime(timezone=True)),
    UniqueConstraint('session_id', 'filename', name='uq_session_filename'),
    CheckConstraint('document_id >= 0 AND page_count >= 0 AND chunk_count >= 0 AND size_bytes >= 0', name='document_counts_nonnegative'),
)
chunks = Table('document_chunks', metadata,
    Column('chunk_id', UUID(as_uuid=True), primary_key=True),
    Column('session_id', String(32), nullable=False),
    Column('document_id', Integer, nullable=False),
    Column('chunk_ordinal', Integer, nullable=False),
    Column('content', Text, nullable=False),
    Column('metadata', JSONB, nullable=False),
    Column('embedding', VECTOR(1024), nullable=False),
    Column('embedding_profile_id', String(64), nullable=False),
    Column('content_sha256', String(64), nullable=False),
    Column('import_source_id', String(64)),
    ForeignKeyConstraint(['session_id', 'document_id'],
                         ['session_documents.session_id', 'session_documents.document_id'], ondelete='CASCADE'),
    UniqueConstraint('session_id', 'document_id', 'chunk_ordinal', name='uq_document_chunk_order'),
    CheckConstraint('chunk_ordinal >= 0', name='chunk_order_nonnegative'),
    CheckConstraint("jsonb_typeof(metadata) = 'object'", name='chunk_metadata_object'),
    CheckConstraint('vector_norm(embedding) > 0', name='chunk_vector_nonzero'),
)
Index('ix_chunk_scope_profile', chunks.c.session_id, chunks.c.embedding_profile_id)
