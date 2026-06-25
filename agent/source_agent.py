from tools.source_tool import source_tool
from utils.deepseek_client import ask_deepseek


def source_agent(question, vectorstore, chat_history):
    """
    Source Agent

    Responsibilities:
    - Retrieve relevant source documents.
    - Explain which PDFs and pages support the user's request.
    - Provide evidence attribution instead of answering the full question.
    """

    # Retrieve documents from Source Tool
    docs = source_tool(
        question,
        vectorstore
    )

    # Source Agent role prompt
    prompt = f"""
You are the Source Agent of a PDF Analysis System.

Your responsibilities are:

1. Identify which PDF chunks are relevant to the user's question.
2. Mention the PDF filename when available.
3. Mention the page number when available.
4. Explain briefly why each source is relevant.
5. Do NOT fully answer the user's question.
6. Focus only on evidence, citation, and source attribution.

User Question:
{question}

Return a clear source list.
"""

    # Generate source explanation
    answer = ask_deepseek(
        prompt,
        docs,
        chat_history
    )

    return {
        "agent": "Source Agent",
        "status": "success",
        "answer": answer,
        "results": docs
    }