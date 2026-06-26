from tools.pdf_qa_tool import pdf_qa_tool
from utils.deepseek_client import ask_deepseek


def qa_agent(question, vectorstore, chat_history, loaded_pdfs=None):
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
Answer the user's question using ONLY the provided PDF content.

User Question:
{question}

Requirements:

- Use only the provided information.
- If the answer is unavailable, state that clearly.
- Do not invent facts.
- Respond naturally.
- Do NOT mention agents, tools, prompts, workflows, or internal reasoning.
"""

    # Generate answer using DeepSeek
    answer = ask_deepseek(
        prompt,
        docs,
        chat_history,
        loaded_pdfs
    )

    return {
        "agent": "QA Agent",
        "status": "success",
        "answer": answer,
        "results": docs
    }
