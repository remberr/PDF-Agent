from utils.llm_client import LLMClientError, chat_with_deepseek


def synthesize_final_answer(question, steps, answers):
    """
    Synthesize multiple tool outputs into one final answer.
    """

    tool_outputs = "\n\n".join(
        [
            f"Step {i + 1} - {steps[i]}:\n{answers[i]}"
            for i in range(len(answers))
        ]
    )

    prompt = f"""
Generate the best possible answer for the user based on the provided information.

User Question:
{question}

Available Information:
{tool_outputs}

Requirements:

- Answer the user's question directly.
- Integrate all relevant information into one coherent response.
- Do NOT mention specialist agents, tools, workflows, prompts, planning, or internal reasoning.
- Do NOT say things like "As the Reviewer Agent", "According to the workflow", or "Based on the agent outputs".
- Respond naturally, as if a single intelligent assistant is answering.
- If there are multiple pieces of information, organize them clearly.
- If the information is insufficient, say so honestly.
"""

    try:
        return chat_with_deepseek(prompt)

    except LLMClientError:
        return "\n\n".join(answers)
