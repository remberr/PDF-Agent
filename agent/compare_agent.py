from tools.compare_tool import compare_tool
from utils.deepseek_client import ask_deepseek


def compare_agent(vectorstore, chat_history):
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
You are the Compare Agent of a PDF Analysis System.

Your responsibilities are:

1. Compare EACH uploaded PDF separately.
2. Mention the filename of each PDF.
3. Identify the main topic of each PDF.
4. Compare their methods, viewpoints, results, and conclusions.
5. Explain similarities and differences clearly.
6. Do NOT ignore any uploaded PDF if its content appears in the context.
7. Finally provide an overall comparison.

Return the result in a clear structured format.
"""

    # Generate comparison using DeepSeek
    answer = ask_deepseek(
        prompt,
        docs,
        chat_history
    )

    return {
        "agent": "Compare Agent",
        "status": "success",
        "answer": answer,
        "results": docs
    }