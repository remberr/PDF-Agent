import os

from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings


def get_embeddings():
    return HuggingFaceEmbeddings(
        model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )


def create_vectorstore(chunks):
    embeddings = get_embeddings()

    vectorstore = FAISS.from_documents(
        documents=chunks,
        embedding=embeddings
    )

    return vectorstore


def save_vectorstore(vectorstore, path="vectorstore/faiss_index"):
    os.makedirs(path, exist_ok=True)
    vectorstore.save_local(path)


def load_vectorstore(path="vectorstore/faiss_index"):
    embeddings = get_embeddings()
    
    return FAISS.load_local(
        path=path,
        embeddings=embeddings,
        all_dangerous_deserialization=True
    )


def vectorstore_exists(path="vectorstore/faiss_index"):
    return os.path.exists(os.path.join(path, "index.faiss"))