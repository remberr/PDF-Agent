"""Pinned dense BGE-M3 contract for PostgreSQL vectors and migration tools."""

import hashlib
import json
from threading import Lock
from types import MappingProxyType

import numpy as np
from langchain_core.embeddings import Embeddings


BGE_PROFILE = MappingProxyType({
    "model": "BAAI/bge-m3",
    "revision": "5617a9f61b028005a4858fdac845db406aefb181",
    "dimension": 1024,
    "pooling": "cls",
    "normalize": True,
    "dtype": "float32",
    "max_seq_length": 8192,
    "batch_size": 1,
    "device": "cpu",
    "newline_policy": "replace_with_space",
})
PROFILE_ID = hashlib.sha256(json.dumps(dict(BGE_PROFILE), sort_keys=True).encode()).hexdigest()
_instance = None
_load_lock = Lock()


def validate_vectors(vectors, *, expected_count: int) -> list[list[float]]:
    """Reject incompatible/corrupt vectors rather than silently normalize them."""
    values = np.asarray(vectors, dtype=np.float32)
    if values.shape != (expected_count, BGE_PROFILE["dimension"]):
        raise ValueError("Embedding count or dimension does not match the profile.")
    if not np.isfinite(values).all():
        raise ValueError("Embedding contains non-finite values.")
    if not np.allclose(np.linalg.norm(values, axis=1), 1, atol=1e-5, rtol=0):
        raise ValueError("Embedding must have unit L2 norm.")
    return values.tolist()


class ValidatedEmbeddings(Embeddings):
    def __init__(self, delegate: Embeddings):
        self._delegate = delegate
        self._encode_lock = Lock()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        with self._encode_lock:
            return validate_vectors(self._delegate.embed_documents(texts), expected_count=len(texts))

    def embed_query(self, text: str) -> list[float]:
        with self._encode_lock:
            return validate_vectors([self._delegate.embed_query(text)], expected_count=1)[0]


def create_bge_embeddings(*, local_files_only: bool = True) -> ValidatedEmbeddings:
    """Runtime is offline by default; downloading is an explicit build operation."""
    from langchain_huggingface import HuggingFaceEmbeddings
    import torch

    encoding = {"batch_size": BGE_PROFILE["batch_size"], "normalize_embeddings": True,
                "precision": "float32"}
    delegate = HuggingFaceEmbeddings(
        model_name=BGE_PROFILE["model"],
        model_kwargs={"revision": BGE_PROFILE["revision"], "device": "cpu",
                      "local_files_only": local_files_only, "trust_remote_code": False,
                      "model_kwargs": {"torch_dtype": torch.float32}},
        encode_kwargs=encoding,
        query_encode_kwargs=dict(encoding),
    )
    if delegate._client.get_sentence_embedding_dimension() != 1024:
        raise ValueError("Loaded model dimension does not match the pinned profile.")
    delegate._client.max_seq_length = BGE_PROFILE["max_seq_length"]
    return ValidatedEmbeddings(delegate)


def get_bge_embeddings() -> ValidatedEmbeddings:
    global _instance
    with _load_lock:
        if _instance is None:
            _instance = create_bge_embeddings()
        return _instance
