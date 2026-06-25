def keyword_tool(vectorstore):
    """
    Keyword Tool

    Responsibilities:
    - Retrieve representative document chunks
      for keyword extraction.
    - Return retrieved documents only.
    - No LLM reasoning is performed here.
    """

    # Retrieve representative chunks
    results = vectorstore.similarity_search(
        "important keywords key concepts terminology",
        k=10
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