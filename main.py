import tempfile

import streamlit as st
from langchain_community.document_loaders import PyPDFLoader

from utils.text_splitter import split_documents
from utils.vectorstore import create_vectorstore
from utils.deepseek_client import ask_deepseek

st.title("📄 PDF Agent")

uploaded_file = st.file_uploader("Upload PDF", type=["pdf"])

if uploaded_file:
    st.success(f"Uploaded: {uploaded_file.name}")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
        tmp_file.write(uploaded_file.getbuffer())
        pdf_path = tmp_file.name

    loader = PyPDFLoader(pdf_path)
    docs = loader.load()

    st.subheader("PDF Information")
    st.write(f"Total Pages: {len(docs)}")

    chunks = split_documents(docs)

    st.subheader("Chunk Information")
    st.write(f"Total Chunks: {len(chunks)}")

    vectorstore = create_vectorstore(chunks)
    st.success("Vector store created successfully!")

    question = st.text_input("Ask a question about the PDF")

    if question:
        results = vectorstore.similarity_search(question, k=3)

        answer = ask_deepseek(question, results)

        st.subheader("Answer")
        st.write(answer)

        st.subheader("Search Results")

        for i, doc in enumerate(results):
            st.markdown(f"### Result {i + 1}")
            st.write(doc.page_content[:1000])

            if "page" in doc.metadata:
                st.caption(f"Page: {doc.metadata['page'] + 1}")

else:
    st.info("Please upload a PDF file first.")