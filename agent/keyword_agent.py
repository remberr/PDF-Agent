from tools.keyword_tool import keyword_tool
from utils.deepseek_client import ask_deepseek


def keyword_agent(vectorstore, chat_history, loaded_pdfs=None):
    """
    Keyword Agent

    Responsibilities:
    - Retrieve representative PDF chunks.
    - Extract important keywords and concepts.
    - Explain the significance of each keyword.
    """

    # Retrieve documents from Keyword Tool
    docs = keyword_tool(
        vectorstore
    )

    # Keyword Agent role prompt
    prompt = """
Extract the important keywords and concepts from the uploaded PDFs.

Requirements:

- Group keywords by PDF.
- Briefly explain each keyword.
- Remove duplicate keywords.
- Provide an overall keyword summary.
- Do NOT mention agents, prompts, workflows, or reasoning.
"""

    # Generate keyword analysis
    answer = ask_deepseek(
        prompt,
        docs,
        chat_history,
        loaded_pdfs
    )

    return {
        "agent": "Keyword Agent",
        "status": "success",
        "answer": answer,
        "results": docs
    }
