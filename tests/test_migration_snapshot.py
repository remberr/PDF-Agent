import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from migration_tools.snapshot import snapshot, verify_snapshot, sha256


class SnapshotTests(unittest.TestCase):
    def test_backup_preserves_wal_and_rejects_overwrite_or_tampering(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'source'
            source.mkdir()
            connection = sqlite3.connect(source / 'sessions.db')
            try:
                connection.execute('PRAGMA journal_mode=WAL')
                connection.execute('CREATE TABLE sessions(session_id TEXT, loaded_pdfs TEXT, messages TEXT, vectorstore_path TEXT, document_count INTEGER)')
                connection.execute('INSERT INTO sessions VALUES(?,?,?,?,?)', ('a'*32, '[]', json.dumps([{'unknown': True}]), None, 0))
                connection.commit()
                destination = root / 'snapshot'
                snapshot(source, destination)
                self.assertEqual(verify_snapshot(destination)['session_count'], 1)
                with self.assertRaises(ValueError):
                    snapshot(source, destination)
                with closing(sqlite3.connect(destination / 'sessions.db')) as backup:
                    self.assertEqual(json.loads(backup.execute('SELECT messages FROM sessions').fetchone()[0]), [{'unknown': True}])
                with (destination / 'sessions.db').open('ab') as output:
                    output.write(b'changed')
                with self.assertRaises(ValueError):
                    verify_snapshot(destination)
            finally:
                connection.close()
