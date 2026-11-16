import unittest
from unittest.mock import Mock, patch

from utils.embeddings import BGE_PROFILE, PROFILE_ID, ValidatedEmbeddings, validate_vectors, create_bge_embeddings


class EmbeddingContractTests(unittest.TestCase):
    def test_profile_is_pinned(self):
        self.assertEqual(BGE_PROFILE['dimension'], 1024)
        self.assertEqual(len(BGE_PROFILE['revision']), 40)
        self.assertEqual(len(PROFILE_ID), 64)

    def test_rejects_wrong_dimension_nonfinite_and_nonunit(self):
        for vector in ([1.] * 384, [float('nan')] * 1024,
                       [float('inf')] * 1024, [0.] * 1024, [1.] * 1024):
            with self.subTest(length=len(vector)), self.assertRaises(ValueError):
                validate_vectors([vector], expected_count=1)

    def test_rejects_wrong_count(self):
        with self.assertRaises(ValueError):
            validate_vectors([], expected_count=1)

    def test_query_and_documents_share_validation(self):
        delegate = Mock()
        delegate.embed_documents.return_value = [[1.] + [0.] * 1023]
        delegate.embed_query.return_value = [1.] * 384
        embeddings = ValidatedEmbeddings(delegate)
        self.assertEqual(embeddings.embed_documents(['fixture'])[0][0], 1.)
        with self.assertRaises(ValueError):
            embeddings.embed_query('fixture')

    def test_empty_batch_does_not_invoke_model(self):
        delegate = Mock()
        self.assertEqual(ValidatedEmbeddings(delegate).embed_documents([]), [])
        delegate.embed_documents.assert_not_called()

    def test_missing_cached_model_does_not_retry_download(self):
        with patch('langchain_huggingface.HuggingFaceEmbeddings', side_effect=OSError('missing cache')) as factory:
            with self.assertRaises(OSError):
                create_bge_embeddings()
        factory.assert_called_once()
        settings = factory.call_args.kwargs['model_kwargs']
        self.assertTrue(settings['local_files_only'])
        self.assertFalse(settings['trust_remote_code'])
        self.assertEqual(settings['revision'], BGE_PROFILE['revision'])

    def test_factory_rejects_model_dimension_mismatch(self):
        delegate = Mock()
        delegate._client.get_sentence_embedding_dimension.return_value = 384
        with patch('langchain_huggingface.HuggingFaceEmbeddings', return_value=delegate):
            with self.assertRaises(ValueError):
                create_bge_embeddings()
