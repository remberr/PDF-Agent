from utils.final_synthesizer import synthesize_final_answer


def reviewer_agent(question, steps, answers):
    """
    Reviewer Agent

    Responsibilities:
    - Review outputs from all specialist agents.
    - Integrate multiple agent responses into
      one coherent final answer.
    - Return the agent name, execution status,
      and synthesized final answer.
    """

    # Call the final synthesizer
    final_answer = synthesize_final_answer(
        question,
        steps,
        answers
    )

    # Return the reviewer output
    return {
        "agent": "Reviewer Agent",
        "status": "success",
        "answer": final_answer
    }