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
Generate a clear summary of the uploaded PDFs.

Requirements:

- Summarize each uploaded PDF separately.
- Mention the filename.
- Explain the main topic.
- Explain the important points.
- Explain the conclusion.
- Provide an overall summary.
- Do NOT mention agents, prompts, workflows, or reasoning.
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