def source_tool(question, vectorstore):
    """
    Source Tool

    Responsibilities:
    - Retrieve source documents related to the user's question.
    - Return retrieved documents only.
    - No LLM reasoning is performed here.
    """

    # Retrieve the most relevant chunks
    results = vectorstore.similarity_search(
        question,
        k=3
    )

    # Return retrieved documents only
    return results
