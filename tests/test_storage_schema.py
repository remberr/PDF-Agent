import unittest

from app.db.schema import metadata


class StorageSchemaTests(unittest.TestCase):
    def test_chunks_require_document_in_same_session(self):
        table = metadata.tables['document_chunks']
        keys = [tuple(fk.column_keys) for fk in table.foreign_key_constraints]
        self.assertIn(('session_id', 'document_id'), keys)
        self.assertEqual(table.c.embedding.type.dim, 1024)

    def test_messages_preserve_payload_and_batch_identity(self):
        table = metadata.tables['session_messages']
        self.assertIn('payload', table.c)
        self.assertIn('batch_id', table.c)
        self.assertEqual([c.name for c in table.primary_key], ['session_id', 'ordinal'])
