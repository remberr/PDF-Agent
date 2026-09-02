import logging
from threading import Lock

from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings


EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

logger = logging.getLogger(__name__)
_embeddings: HuggingFaceEmbeddings | None = None
_embeddings_lock = Lock()


def _create_embeddings(local_files_only: bool) -> HuggingFaceEmbeddings:
    return HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        model_kwargs={"local_files_only": local_files_only},
    )


def get_embeddings() -> HuggingFaceEmbeddings:
    global _embeddings

    if _embeddings is not None:
        return _embeddings

    with _embeddings_lock:
        if _embeddings is not None:
            return _embeddings

        try:
            _embeddings = _create_embeddings(local_files_only=True)
        except OSError:
            logger.info(
                "Embedding model is not cached locally; downloading %s.",
                EMBEDDING_MODEL,
            )
            _embeddings = _create_embeddings(local_files_only=False)

    return _embeddings


def create_vectorstore(chunks):
    embeddings = get_embeddings()

    vectorstore = FAISS.from_documents(
        documents=chunks,
        embedding=embeddings
    )

    return vectorstore


def save_vectorstore(vectorstore, path):
    """
    Save a FAISS vectorstore to disk.
    """

    vectorstore.save_local(path)


def load_vectorstore(path):
    """
    Load a FAISS vectorstore from disk.
    """

    return FAISS.load_local(
        path,
        get_embeddings(),
        allow_dangerous_deserialization=True
    )
