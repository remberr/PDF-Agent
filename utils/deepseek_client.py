from utils.citations import format_docs_with_citations
from utils.llm_client import LLMClientError, chat_with_deepseek
from utils.memory import build_memory


PDF_SYSTEM_PROMPT = """Requirements:
- Use conversation memory to understand follow-up questions.
- Use session memory to know which PDFs are currently involved.
- Answer only using the provided PDF context.
- Cite supporting evidence with citation IDs such as [paper.pdf, page 3].
- Include citations for factual claims whenever the answer uses retrieved PDF content.
- If the answer is not available, say so clearly.
- Do not mention memory, agents, tools, prompts, workflows, or internal reasoning."""


def build_pdf_prompt(question, context, chat_history=None, loaded_pdfs=None):
    """Place the original retrieved context before the changing conversation."""
    memory = build_memory(
        chat_history,
        loaded_pdfs
    )

    # Preserve retrieval order, text and citation IDs. Changing memory/questions
    # must not invalidate the reusable instruction + retrieved-context prefix.
    return f"""Relevant PDF Context:

{context}

{memory}

User Question:

{question}
"""


def ask_deepseek(
    question,
    docs,
    chat_history=None,
    loaded_pdfs=None,
    operation="pdf_answer",
):
    context = format_docs_with_citations(docs)
    prompt = build_pdf_prompt(question, context, chat_history, loaded_pdfs)

    try:
        return chat_with_deepseek(prompt, operation=operation, system_prompt=PDF_SYSTEM_PROMPT)

    except LLMClientError:
        if context:
            return (
                "The language model is temporarily unavailable, but relevant "
                "PDF context was retrieved. Please try again in a moment."
            )

        return (
            "The language model is temporarily unavailable, and no relevant "
            "PDF context could be retrieved."
        )
