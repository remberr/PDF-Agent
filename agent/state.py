from typing import TypedDict, List, Any


class AgentState(TypedDict):
    question: str

    steps: List[str]
    current_step: str

    answers: List[str]
    answer: str

    results: List[Any]

    vectorstore: Any
    chat_history: list