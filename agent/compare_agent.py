from tools.compare_tool import compare_tool
from utils.deepseek_client import ask_deepseek


def compare_agent(vectorstore, chat_history, loaded_pdfs=None):
    """
    Compare Agent

    Responsibilities:
    - Retrieve representative PDF chunks.
    - Compare uploaded PDFs by topic, method,
      similarity, difference, and conclusion.
    - Generate a structured comparison.
    """

    # Retrieve documents from Compare Tool
    docs = compare_tool(vectorstore)

    # Compare Agent role prompt
    prompt = """
Compare the uploaded PDFs.

Requirements:

- Compare the topics.
- Compare the methods.
- Compare the conclusions.
- Explain similarities.
- Explain differences.
- Mention filenames.
- Do NOT mention agents, prompts, workflows, or reasoning.
"""

    # Generate comparison using DeepSeek
    answer = ask_deepseek(
        prompt,
        docs,
        chat_history,
        loaded_pdfs
    )

    return {
        "agent": "Compare Agent",
        "status": "success",
        "answer": answer,
        "results": docs
    }
