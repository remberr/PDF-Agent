from tools.source_tool import source_tool


def _is_chinese(text):
    return any("\u4e00" <= character <= "\u9fff" for character in text)


def _source_excerpt(text, max_length=240):
    excerpt = " ".join(text.split())

    if len(excerpt) <= max_length:
        return excerpt

    return f"{excerpt[:max_length].rstrip()}..."


def format_source_answer(question, docs):
    """
    Format retrieved documents as stable citations without an LLM call.
    """

    chinese = _is_chinese(question)
    lines = []
    seen_citations = set()

    for doc in docs:
        source = doc.metadata.get("source", "Unknown Source")
        page = doc.metadata.get("page", 0) + 1
        citation_id = f"{source}, page {page}"

        if citation_id in seen_citations:
            continue

        seen_citations.add(citation_id)
        doc.metadata["citation_id"] = citation_id
        excerpt = _source_excerpt(doc.page_content)
        lines.append(f"- [{citation_id}] - {excerpt}")

    if not lines:
        return "未找到相关 PDF 来源。" if chinese else "No relevant PDF sources were found."

    heading = "相关来源：" if chinese else "Supporting sources:"
    return f"{heading}\n\n" + "\n".join(lines)


def source_agent(question, vectorstore, chat_history, loaded_pdfs=None):
    """
    Source Agent

    Responsibilities:
    - Retrieve relevant source documents.
    - Format PDF filenames, pages, and excerpts as stable citations.
    - Avoid an unnecessary LLM request for deterministic source metadata.
    """

    # Retrieve documents from Source Tool
    docs = source_tool(
        question,
        vectorstore
    )

    answer = format_source_answer(question, docs)

    return {
        "agent": "Source Agent",
        "status": "success",
        "answer": answer,
        "results": docs
    }
