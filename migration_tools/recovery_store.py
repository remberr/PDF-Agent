"""Explicit offline recovery adapter; never part of the running API."""
import json
import re
from pathlib import Path
from migration_tools.import_legacy import RestrictedDocstoreUnpickler
from utils.embeddings import PROFILE_ID, get_bge_embeddings, validate_vectors


def load_recovery_store(root, session_id, *, trusted=False, embeddings=None):
    if not trusted:
        raise ValueError('A trusted locally generated recovery artifact is required.')
    if not re.fullmatch('[a-f0-9]{32}', session_id):
        raise ValueError('Invalid session ID.')
    root = Path(root).resolve()
    profile = json.loads((root / 'embedding-profile.json').read_text(encoding='utf-8'))
    if profile.get('profile_id') != PROFILE_ID:
        raise ValueError('Recovery profile mismatch; do not use the old MiniLM image.')
    folder = (root / 'vectorstores' / session_id).resolve()
    if not folder.is_relative_to(root):
        raise ValueError('Recovery path escapes root.')
    import faiss
    from langchain_community.vectorstores import FAISS
    from langchain_community.vectorstores.utils import DistanceStrategy
    index = faiss.read_index(str(folder / 'index.faiss'))
    if index.d != 1024:
        raise ValueError('Recovery vector dimension mismatch.')
    validate_vectors([index.reconstruct(i) for i in range(index.ntotal)], expected_count=index.ntotal)
    with (folder / 'index.pkl').open('rb') as source:
        docstore, mapping = RestrictedDocstoreUnpickler(source).load()
    if set(mapping) != set(range(index.ntotal)):
        raise ValueError('Recovery mapping mismatch.')
    return FAISS(embeddings if embeddings is not None else get_bge_embeddings(), index,
                 docstore, mapping, distance_strategy=DistanceStrategy.MAX_INNER_PRODUCT)
