from tools.pdf_qa_tool import pdf_qa_tool
from utils.deepseek_client import ask_deepseek


def qa_agent(question, vectorstore, chat_history):
    """
    QA Agent

    Responsibilities:
    - Retrieve relevant PDF content.
    - Answer the user's question based only on PDF evidence.
    - Avoid hallucinating information not found in the PDFs.
    """

    # Retrieve documents from QA Tool
    docs = pdf_qa_tool(
        question,
        vectorstore
    )

    # QA Agent role prompt
    prompt = f"""
You are the QA Agent of a PDF Analysis System.

Your responsibilities are:

1. Answer the user's question based only on the provided PDF content.
2. Use the retrieved evidence carefully.
3. Do not invent information that is not in the PDFs.
4. If the answer is not available in the PDF content, say so clearly.
5. Keep the answer clear, direct, and useful.
6. Mention PDF filenames or pages if they are relevant.

User Question:
{question}
"""

    # Generate answer using DeepSeek
    answer = ask_deepseek(
        prompt,
        docs,
        chat_history
    )

    return {
        "agent": "QA Agent",
        "status": "success",
        "answer": answer,
        "results": docs
    }