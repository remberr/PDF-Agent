def format_docs_with_citations(docs):
    """
    Format retrieved documents with stable citation IDs.
    """

    formatted_docs = []

    for doc in docs:
        source = doc.metadata.get("source", "Unknown Source")
        page = doc.metadata.get("page", 0) + 1
        citation_id = f"{source}, page {page}"

        doc.metadata["citation_id"] = citation_id

        formatted_docs.append(
            (
                f"Citation: [{citation_id}]\n"
                f"PDF: {source}\n"
                f"Page: {page}\n"
                f"Content:\n{doc.page_content}"
            )
        )

    return "\n\n".join(formatted_docs)
