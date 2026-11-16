import io
import unittest
from unittest.mock import patch, Mock
from fastapi import UploadFile
from langchain_core.documents import Document
from app.services.pdf_service import load_pdf_into_session


class AtomicUploadTests(unittest.IsolatedAsyncioTestCase):
    async def test_encoding_failure_does_not_mutate_session_or_commit(self):
        session = {'session_id': 'a'*32, 'loaded_pdfs': [], 'document_count': 0, 'vectorstore': None}
        model = Mock()
        model.embed_documents.side_effect = RuntimeError('fixture encoding failure')
        with patch('app.services.pdf_service.parse_pdf_documents', return_value=[Document(page_content='test', metadata={'source':'test.pdf','page':0})]), \
             patch('app.services.pdf_service.get_bge_embeddings', return_value=model), \
             patch('app.services.pdf_service.commit_document') as commit:
            with self.assertRaises(RuntimeError):
                await load_pdf_into_session(session, UploadFile(filename='test.pdf', file=io.BytesIO(b'pdf')))
        self.assertEqual(session['loaded_pdfs'], [])
        self.assertEqual(session['document_count'], 0)
        commit.assert_not_called()

    async def test_success_updates_only_after_transaction(self):
        session = {'session_id': 'a'*32, 'loaded_pdfs': [], 'document_count': 0, 'vectorstore': None}
        refreshed = {**session, 'loaded_pdfs':['test.pdf'], 'document_count':1, 'vectorstore':object()}
        model = Mock()
        model.embed_documents.return_value = [[1.0] + [0.0]*1023]
        def commit(*args, **kwargs):
            self.assertEqual(session['loaded_pdfs'], [])
            return True
        with patch('app.services.pdf_service.parse_pdf_documents', return_value=[Document(page_content='test', metadata={'source':'test.pdf','page':0})]), \
             patch('app.services.pdf_service.get_bge_embeddings', return_value=model), \
             patch('app.services.pdf_service.commit_document', side_effect=commit), \
             patch('app.services.pdf_service.get_session', return_value=refreshed):
            self.assertTrue(await load_pdf_into_session(session, UploadFile(filename='test.pdf', file=io.BytesIO(b'pdf'))))
        self.assertEqual(session['loaded_pdfs'], ['test.pdf'])
