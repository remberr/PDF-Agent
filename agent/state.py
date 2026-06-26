from typing import TypedDict, List, Any


class CollaborationNotes(TypedDict):
    # Agent name
    agent: str

    # Execution status
    status: str

    # Coordinated intermediate answer
    answer: str

    # Contradictions, weak claims, or quality issues
    issues: List[str]

    # Information needed to improve the final answer
    missing_information: List[str]

    # Suggestions for the reviewer or future workflow
    recommendations: List[str]

    # Whether another specialist step should be executed
    needs_revision: bool

    # Specialist steps requested for lightweight revision
    next_steps: List[str]


def empty_collaboration_notes() -> CollaborationNotes:
    """
    Build the default Collaboration Agent state.
    """

    return {
        "agent": "Collaboration Agent",
        "status": "skipped",
        "answer": "",
        "issues": [],
        "missing_information": [],
        "recommendations": [],
        "needs_revision": False,
        "next_steps": []
    }


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

    # Collaboration analysis before final review
    collaboration_notes: CollaborationNotes

    # Number of lightweight revision attempts
    revision_count: int

    # FAISS vector database
    vectorstore: Any

    # Uploaded PDF filenames in the current session
    loaded_pdfs: List[str]

    # Chat history
    chat_history: list


def create_initial_agent_state(
    question,
    vectorstore,
    chat_history,
    loaded_pdfs=None
) -> AgentState:
    """
    Build the initial LangGraph state for a user request.
    """

    return {
        "question": question,
        "steps": [],
        "current_step": "",
        "answers": [],
        "answer": "",
        "results": [],
        "collaboration_notes": empty_collaboration_notes(),
        "revision_count": 0,
        "vectorstore": vectorstore,
        "loaded_pdfs": loaded_pdfs or [],
        "chat_history": chat_history
    }
