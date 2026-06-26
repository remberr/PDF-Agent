def pdf_qa_tool(question, vectorstore):
    """
    PDF QA Tool

    Responsibilities:
    - Retrieve document chunks related to the user's question.
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
