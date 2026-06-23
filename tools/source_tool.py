def source_tool(question, vectorstore):
    """
    Retrieve source documents related
    to the user's question.

    Parameters:
        question: User's question
        vectorstore: FAISS vector database

    Returns:
        results: Retrieved document chunks
    """

    # Retrieve the most relevant chunks
    # from the vector database
    results = vectorstore.similarity_search(question, k=3)
    return results