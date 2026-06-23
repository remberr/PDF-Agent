import tempfile

import streamlit as st
from langchain_community.document_loaders import PyPDFLoader

from utils.text_splitter import split_documents
from utils.vectorstore import create_vectorstore
from utils.deepseek_client import ask_deepseek


# Page title
st.title("📄 PDF Agent")


# Initialize session state
# These variables will be kept while Streamlit is running
if "all_docs" not in st.session_state:
    st.session_state.all_docs = []

if "loaded_pdfs" not in st.session_state:
    st.session_state.loaded_pdfs = []

if "messages" not in st.session_state:
    st.session_state.messages = []

if "vectorstore" not in st.session_state:
    st.session_state.vectorstore = None


# Upload PDFs
uploaded_files = st.file_uploader(
    "Upload PDF",
    type=["pdf"],
    accept_multiple_files=True
)


# Read newly uploaded PDFs
if uploaded_files:

    for uploaded_file in uploaded_files:

        # Skip PDF if it has already been loaded
        if uploaded_file.name in st.session_state.loaded_pdfs:
            continue

        # Save uploaded PDF as a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            tmp_file.write(uploaded_file.getbuffer())
            pdf_path = tmp_file.name

        # Load PDF content
        loader = PyPDFLoader(pdf_path)
        docs = loader.load()

        # Save PDF filename in metadata
        for doc in docs:
            doc.metadata["source"] = uploaded_file.name

        # Save documents into session state
        st.session_state.all_docs.extend(docs)

        # Record loaded PDF filename
        st.session_state.loaded_pdfs.append(uploaded_file.name)

        st.success(f"Loaded PDF: {uploaded_file.name}")

    # Rebuild vectorstore after adding new PDFs
    if st.session_state.all_docs:

        with st.spinner("Building vectorstore..."):

            chunks = split_documents(st.session_state.all_docs)
            st.session_state.vectorstore = create_vectorstore(chunks)
        
        st.success("Vectorstore built successfully!")


# Display loaded PDFs
st.subheader("Loaded PDFs")

if st.session_state.loaded_pdfs:

    for pdf_name in st.session_state.loaded_pdfs:
        st.write(f"✅ {pdf_name}")

    st.write(f"Total PDFs loaded: {len(st.session_state.loaded_pdfs)}")

else:
    st.info("No PDF has been loaded yet.")


# Clear all PDFs and chat history
if st.button("Clear all PDFs and chat history"):

    st.session_state.all_docs = []
    st.session_state.loaded_pdfs = []
    st.session_state.messages = []
    st.session_state.vectorstore = None

    st.success("All PDFs and chat history have been cleared.")

    st.rerun()


# Display previous chat messages
for message in st.session_state.messages:

    with st.chat_message(message["role"]):
        st.markdown(message["content"])


# Chat input
question = st.chat_input("Ask a question about the PDFs")

if question:

    # Check whether vectorstore exists
    if st.session_state.vectorstore is None:

        st.warning("Please upload a PDF file first.")
    
    else:

        # Save user question
        st.session_state.messages.append({"role": "user", "content": question})

        # Display user question
        with st.chat_message("user"):
            st.markdown(question)
        
        # Retrieve top 3 relevant chunks from FAISS
        results = st.session_state.vectorstore.similarity_search(question, k=3)

        # Generate answer with DeepSeek
        answer = ask_deepseek(
            question,
            results,
            st.session_state.messages
        )

        # Display assistant answer
        with st.chat_message("assistant"):

            st.markdown(answer)

            # Display source chunks
            with st.expander("Sources"):

                for i, doc in enumerate(results):

                    source = doc.metadata.get("source", "Unknown Source")
                    page = doc.metadata.get("page", 0) + 1
                    
                    st.markdown(f"**Source {i + 1}**")
                    st.write(f"PDF: {source}")
                    st.write(f"Page: {page}")
                    st.write(doc.page_content[:800])
        
        # Save assistant answer
        st.session_state.messages.append({"role": "assistant", "content": answer})