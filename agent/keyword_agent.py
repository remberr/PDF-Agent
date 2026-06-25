from tools.keyword_tool import keyword_tool
from utils.deepseek_client import ask_deepseek


def keyword_agent(vectorstore, chat_history):
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
You are the Keyword Agent of a PDF Analysis System.

Your responsibilities are:

1. Analyze ALL uploaded PDFs.
2. Extract the most important keywords or concepts from EACH PDF.
3. Mention the filename for each PDF.
4. Explain each keyword briefly.
5. Do NOT repeat duplicate keywords.
6. Finally summarize the overall important concepts across all PDFs.

Return a well-structured answer using bullet points.
"""

    # Generate keyword analysis
    answer = ask_deepseek(
        prompt,
        docs,
        chat_history
    )

    return {
        "agent": "Keyword Agent",
        "status": "success",
        "answer": answer,
        "results": docs
    }