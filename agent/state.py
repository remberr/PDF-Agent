from typing import TypedDict, List, Any


class AgentState(TypedDict):
    # User question
    question: str

    # Planned agent steps
    steps: List[str]

    # Current executing step
    current_step: str

    # Output from specific agents
    answers: List[str]

    # Final answer from Reviewer Agent
    answer: str

    # Retrieved source documents
    results: List[Any]

    # FAISS vector database
    vectorstore: Any

    # Chat history
    chat_history: list