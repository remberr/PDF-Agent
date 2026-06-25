def pdf_summary_tool(vectorstore):
    """
    PDF Summary Tool

    Responsibilities:
    - Retrieve representative document chunks
      from all uploaded PDFs.
    - Return the retrieved documents only.
    - No LLM reasoning is performed here.
    """

    # Retrieve more chunks to cover all PDFs
    results = vectorstore.similarity_search(
        "document summary main topic overview",
        k=30
    )

    # Keep only a few chunks from each PDF
    grouped_docs = {}
    selected_docs = []

    for doc in results:

        source = doc.metadata.get(
            "source",
            "Unknown Source"
        )

        if source not in grouped_docs:
            grouped_docs[source] = 0

        if grouped_docs[source] < 3:

            selected_docs.append(doc)
            grouped_docs[source] += 1

    # Return retrieved documents only
    return selected_docs