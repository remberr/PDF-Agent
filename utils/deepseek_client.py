from utils.citations import format_docs_with_citations
from utils.llm_client import LLMClientError, chat_with_deepseek
from utils.memory import build_memory


def ask_deepseek(question, docs, chat_history=None, loaded_pdfs=None):

    context = format_docs_with_citations(docs)

    memory = build_memory(
        chat_history,
        loaded_pdfs
    )

    prompt = f"""
{memory}

Relevant PDF Context:

{context}

User Question:

{question}

Requirements:
- Use conversation memory to understand follow-up questions.
- Use session memory to know which PDFs are currently involved.
- Answer only using the provided PDF context.
- Cite supporting evidence with citation IDs such as [paper.pdf, page 3].
- Include citations for factual claims whenever the answer uses retrieved PDF content.
- If the answer is not available, say so clearly.
- Do not mention memory, agents, tools, prompts, workflows, or internal reasoning.
"""

    try:
        return chat_with_deepseek(prompt)

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
