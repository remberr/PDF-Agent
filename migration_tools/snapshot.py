"""Non-destructive legacy snapshot. Never deserialize an untrusted pickle."""
import hashlib
import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot(source, destination):
    """Caller must stop legacy writers; SQLite backup includes committed WAL data."""
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination.exists():
        raise ValueError('Snapshot destination must be new.')
    if not (source / 'sessions.db').is_file():
        raise ValueError('Source SQLite database is missing.')
    destination.mkdir(parents=True)
    with closing(sqlite3.connect((source / 'sessions.db').as_uri() + '?mode=ro', uri=True)) as original:
        with closing(sqlite3.connect(destination / 'sessions.db')) as backup:
            original.backup(backup)
    with closing(sqlite3.connect(destination / 'sessions.db')) as backup:
        backup.row_factory = sqlite3.Row
        rows = [dict(row) for row in backup.execute('SELECT * FROM sessions ORDER BY session_id')]
    files = {'sessions.db': sha256(destination / 'sessions.db')}
    profile = source / 'embedding-profile.json'
    if profile.is_file():
        shutil.copy2(profile, destination / profile.name)
        files[profile.name] = sha256(destination / profile.name)
    for row in rows:
        sid = row['session_id']
        import re
        if not isinstance(sid, str) or not re.fullmatch('[a-f0-9]{32}', sid):
            raise ValueError('Invalid session identifier.')
        names = json.loads(row['loaded_pdfs'])
        if not names:
            continue
        index = (source / 'vectorstores' / sid).resolve()
        if index.parent != (source / 'vectorstores').resolve():
            raise ValueError('Index escapes source directory.')
        configured = Path(row['vectorstore_path']).resolve()
        if configured != index:
            raise ValueError('Stored index path does not match the session directory.')
        target = destination / 'vectorstores' / sid
        target.mkdir(parents=True)
        for name in ('index.faiss', 'index.pkl'):
            before = sha256(index / name)
            shutil.copy2(index / name, target / name)
            after = sha256(index / name)
            if before != after or sha256(target / name) != before:
                raise ValueError('Index changed during snapshot; freeze writers and retry.')
            files[str((target / name).relative_to(destination)).replace('\\', '/')] = before
    manifest = {'format': 1, 'files': files, 'session_count': len(rows)}
    (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest


def verify_snapshot(directory):
    directory = Path(directory).resolve()
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    for name, expected in manifest['files'].items():
        path = (directory / name).resolve()
        if not path.is_relative_to(directory) or sha256(path) != expected:
            raise ValueError('Snapshot integrity check failed.')
    return manifest
