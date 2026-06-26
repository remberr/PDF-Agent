from tools.source_tool import source_tool
from utils.deepseek_client import ask_deepseek


def source_agent(question, vectorstore, chat_history, loaded_pdfs=None):
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

- Use the citation IDs from the provided context, such as [paper.pdf, page 3].
- For each source, include the PDF filename and page number.
- Use this format when possible: [paper.pdf, page 3] - why it is relevant.
- Do NOT answer the original question again.
- Do NOT mention agents, prompts, workflows, or internal reasoning.
"""

    # Generate source explanation
    answer = ask_deepseek(
        prompt,
        docs,
        chat_history,
        loaded_pdfs
    )

    return {
        "agent": "Source Agent",
        "status": "success",
        "answer": answer,
        "results": docs
    }
