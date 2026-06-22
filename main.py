import streamlit as st
import tempfile

from langchain_community.document_loaders import PyPDFLoader
from utils.text_splitter import split_documents

st.title("📄 PDF Agent")

uploaded_file = st.file_uploader(
    "Upload PDF",
    type=["pdf"]
)

if uploaded_file:

    st.success(f"Uploaded: {uploaded_file.name}")

    # 保存临时文件
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
        tmp_file.write(uploaded_file.getbuffer())
        pdf_path = tmp_file.name

    # 读取 PDF
    loader = PyPDFLoader(pdf_path)
    docs = loader.load()

    st.subheader("PDF Information")
    st.write(f"Total Pages: {len(docs)}")

    # 文本切块
    chunks = split_documents(docs)

    st.subheader("Chunk Information")
    st.write(f"Total Chunks: {len(chunks)}")

    # 显示第一个 Chunk
    if chunks:
        st.subheader("First Chunk Preview")
        st.write(chunks[0].page_content[:1000])