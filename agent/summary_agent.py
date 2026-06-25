from tools.pdf_summary_tool import pdf_summary_tool
from utils.deepseek_client import ask_deepseek


def summary_agent(vectorstore, chat_history):
    """
    Summary Agent

    Responsibilities:
    - Retrieve representative PDF chunks.
    - Summarize each uploaded PDF separately.
    - Generate a final overall summary.
    """

    # Retrieve documents from Summary Tool
    docs = pdf_summary_tool(
        vectorstore
    )

    # Summary Agent role prompt
    prompt = """
You are the Summary Agent of a PDF Analysis System.

Your responsibilities are:

1. Summarize EACH uploaded PDF separately.
2. Mention the filename of each PDF.
3. Explain the main topic.
4. Summarize the important points.
5. Explain the conclusion of each PDF.
6. Do NOT ignore any uploaded PDF.
7. Finally provide a short overall summary.

Return a well-structured answer.
"""

    # Generate summary
    answer = ask_deepseek(
        prompt,
        docs,
        chat_history
    )

    return {
        "agent": "Summary Agent",
        "status": "success",
        "answer": answer,
        "results": docs
    }