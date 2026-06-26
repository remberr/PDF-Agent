def compare_tool(vectorstore):
    """
    Compare Tool

    Responsibilities:
    - Retrieve representative document chunks
      for cross-PDF comparison.
    - Return retrieved documents only.
    - No LLM reasoning is performed here.
    """

    # Retrieve more chunks to cover multiple PDFs
    results = vectorstore.similarity_search(
        "compare main topics methods results conclusions differences similarities",
        k=30
    )

    # Keep only a few chunks from each PDF
    grouped_docs = {}
    selected_docs = []

    for doc in results:
        source = doc.metadata.get("source", "Unknown Source")

        if source not in grouped_docs:
            grouped_docs[source] = 0

        if grouped_docs[source] < 3:
            selected_docs.append(doc)
            grouped_docs[source] += 1

    # Return retrieved documents only
    return selected_docs
