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
Identify the supporting sources for the user's question.

User Question:
{question}

Requirements:

- Mention the relevant PDF filenames.
- Mention page numbers when available.
- Explain briefly why each source is relevant.
- Do NOT answer the original question again.
- Do NOT mention agents, prompts, workflows, or internal reasoning.
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