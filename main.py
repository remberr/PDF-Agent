import os
import tempfile

import streamlit as st
from langchain_community.document_loaders import PyPDFLoader

from utils.text_splitter import split_documents
from utils.vectorstore import create_vectorstore

from agent.graph_agent import build_pdf_agent_graph
from agent.state import create_initial_agent_state, empty_collaboration_notes


# Page title
st.title("PDF Agent")


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

if "temp_pdf_paths" not in st.session_state:
    st.session_state.temp_pdf_paths = []


def cleanup_temp_pdfs():
    """
    Remove temporary PDF files created during upload processing.
    """

    remaining_paths = []

    for pdf_path in st.session_state.get("temp_pdf_paths", []):
        try:
            if os.path.exists(pdf_path):
                os.remove(pdf_path)

        except OSError:
            remaining_paths.append(pdf_path)

    st.session_state.temp_pdf_paths = remaining_paths


def display_sources(results):
    """
    Display retrieved source documents.
    """

    if results:

        with st.expander("Sources"):
            seen_sources = set()

            for i, doc in enumerate(results):

                source = doc.metadata.get("source", "Unknown Source")
                page = doc.metadata.get("page", 0) + 1
                citation_id = doc.metadata.get(
                    "citation_id",
                    f"{source}, page {page}"
                )
                source_key = (citation_id, source, page)

                if source_key in seen_sources:
                    continue

                seen_sources.add(source_key)

                st.markdown(f"**[{citation_id}]**")
                st.write(doc.page_content[:800])


def display_workflow_trace(steps, collaboration_notes=None, revision_count=0):
    """
    Display the agent workflow trace for a completed response.
    """

    collaboration_notes = collaboration_notes or {}

    if not steps:
        return

    with st.expander("Workflow trace"):

        st.markdown("**Planned specialist steps**")
        st.caption(" -> ".join(steps))

        if len(steps) <= 1:
            st.info("Single-agent request: skipped collaboration and retry.")

        else:
            st.markdown("**Collaboration Agent**")

            status = collaboration_notes.get("status", "not_run")
            st.write(f"Status: {status}")

            issues = collaboration_notes.get("issues", [])
            missing_information = collaboration_notes.get(
                "missing_information",
                []
            )
            recommendations = collaboration_notes.get("recommendations", [])
            needs_revision = collaboration_notes.get("needs_revision", False)
            next_steps = collaboration_notes.get("next_steps", [])

            if issues:
                st.write("Issues:")
                for issue in issues:
                    st.write(f"- {issue}")

            if missing_information:
                st.write("Missing information:")
                for item in missing_information:
                    st.write(f"- {item}")

            if recommendations:
                st.write("Recommendations:")
                for recommendation in recommendations:
                    st.write(f"- {recommendation}")

            st.markdown("**Revision Controller**")
            st.write(f"Revision attempts: {revision_count}")

            if needs_revision and next_steps:
                st.write(
                    "Requested retry steps: "
                    + " -> ".join(next_steps)
                )
            else:
                st.write("No retry requested.")


# Upload PDFs
uploaded_files = st.file_uploader(
    "Upload PDF",
    type=["pdf"],
    accept_multiple_files=True
)


# Read newly uploaded PDFs
new_pdf_loaded = False

if uploaded_files:

    for uploaded_file in uploaded_files:

        # Skip PDF if it has already been loaded
        if uploaded_file.name in st.session_state.loaded_pdfs:
            continue

        # Save uploaded PDF as a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            tmp_file.write(uploaded_file.getbuffer())
            pdf_path = tmp_file.name

        st.session_state.temp_pdf_paths.append(pdf_path)

        try:
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

            new_pdf_loaded = True

            st.success(f"Loaded PDF: {uploaded_file.name}")

        finally:
            cleanup_temp_pdfs()

# Rebuild vectorstore after adding new PDFs
if st.session_state.all_docs and new_pdf_loaded:

    with st.spinner("Building vectorstore..."):

        chunks = split_documents(st.session_state.all_docs)
        st.session_state.vectorstore = create_vectorstore(chunks)
    
    st.success("Vectorstore built successfully!")


# Display loaded PDFs
st.subheader("Loaded PDFs")

if st.session_state.loaded_pdfs:

    for pdf_name in st.session_state.loaded_pdfs:
        st.write(f"- {pdf_name}")

    st.write(f"Total PDFs loaded: {len(st.session_state.loaded_pdfs)}")

else:
    st.info("No PDF has been loaded yet.")


# Clear all PDFs and chat history
if st.button("Clear all PDFs and chat history"):

    cleanup_temp_pdfs()

    st.session_state.all_docs = []
    st.session_state.loaded_pdfs = []
    st.session_state.messages = []
    st.session_state.vectorstore = None
    st.session_state.temp_pdf_paths = []

    st.success("All PDFs and chat history have been cleared.")

    st.rerun()


# Display previous chat messages
for message in st.session_state.messages:

    with st.chat_message(message["role"]):

        st.markdown(message["content"])

        # Display sources
        if (message["role"] == "assistant" and "sources" in message and message["sources"]):

            display_sources(message["sources"])

        # Display detailed workflow trace
        if (message["role"] == "assistant" and "steps" in message and message["steps"]):

            display_workflow_trace(
                message["steps"],
                message.get("collaboration_notes", {}),
                message.get("revision_count", 0)
            )


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
        
        # Build and run LangGraph PDF Agent
        pdf_agent_graph = build_pdf_agent_graph()

        try:
            agent_result = pdf_agent_graph.invoke(
                create_initial_agent_state(
                    question,
                    st.session_state.vectorstore,
                    st.session_state.messages,
                    st.session_state.loaded_pdfs
                )
            )

        except Exception as exc:
            agent_result = {
                "answer": (
                    "Sorry, the PDF Agent could not complete this request. "
                    f"Error: {exc}"
                ),
                "answers": [],
                "results": [],
                "steps": [],
                "collaboration_notes": empty_collaboration_notes(),
                "revision_count": 0
            }

        # Get graph outputs
        answer = agent_result.get("answer", "")
        answers = agent_result.get("answers", [])

        # Fallback:
        # If final answer is empty,
        # combine all tool outputs manually
        if not answer and answers:
            answer = "\n\n".join(answers)

        results = agent_result.get("results", [])
        steps = agent_result.get("steps", [])
        collaboration_notes = agent_result.get("collaboration_notes", {})
        revision_count = agent_result.get("revision_count", 0)

        # Display assistant answer
        with st.chat_message("assistant"):

            st.markdown(answer)

            # Display source documents
            display_sources(results)

            # Display detailed workflow trace
            if steps:
                display_workflow_trace(
                    steps,
                    collaboration_notes,
                    revision_count
                )
            
        # Save assistant answer with steps and sources
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": answer,
                "steps": steps,
                "collaboration_notes": collaboration_notes,
                "revision_count": revision_count,
                "sources": results
            }
        )
        
