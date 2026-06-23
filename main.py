import tempfile

import streamlit as st
from langchain_community.document_loaders import PyPDFLoader

from utils.text_splitter import split_documents
from utils.vectorstore import create_vectorstore
from utils.deepseek_client import ask_deepseek


st.title("📄 PDF Agent")

uploaded_files = st.file_uploader(
    "Upload PDF",
    type=["pdf"],
    accept_multiple_files=True
)

if uploaded_files:
    st.success(f"Uploaded: {len(uploaded_files)} PDF file(s).")

    all_docs = []
    
    for uploaded_file in uploaded_files:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            tmp_file.write(uploaded_file.getbuffer())
            pdf_path = tmp_file.name

        loader = PyPDFLoader(pdf_path)
        docs = loader.load()

        for doc in docs:
            doc.metadata["source"] = uploaded_file.name

        all_docs.extend(docs)

    st.write(f"Total Pages: {len(all_docs)}")

    chunks = split_documents(all_docs)
    st.write(f"Total Chunks: {len(chunks)}")

    file_names = [file.name for file in uploaded_files]

    if (
        "vectorstore" not in st.session_state
        or st.session_state.get("uploaded_files") != file_names
    ):
        with st.spinner("Creating vector store..."):
            st.session_state.vectorstore = create_vectorstore(chunks)
            st.session_state.uploaded_files = file_names
        
        st.success("Vector store created successfully!")
    else:
        st.success("Using cached vector store.")

    vectorstore = st.session_state.vectorstore

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    question = st.chat_input("Ask a question about the PDFs")

    if question:
        st.session_state.messages.append({"role": "user", "content": question})
        results = vectorstore.similarity_search(question, k=3)

        with st.chat_message("user"):
            st.markdown(question)
        
        results = vectorstore.similarity_search(question, k=3)

        answer = ask_deepseek(
            question,
            results,
            st.session_state.messages
        )

        with st.chat_message("assistant"):
            st.markdown(answer)

            with st.expander("Sources"):
                for i, doc in enumerate(results):
                    source = doc.metadata.get("source", "Unknown Source")
                    page = doc.metadata.get("page", 0) + 1
                    
                    st.markdown(f"**Source {i + 1}**")
                    st.write(f"PDF: {source}")
                    st.write(f"Page: {page}")
                    st.write(doc.page_content[:800])
        
        st.session_state.messages.append({"role": "assistant", "content": answer})

else:
    st.info("Please upload a PDF file first.")