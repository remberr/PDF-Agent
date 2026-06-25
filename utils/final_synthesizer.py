import os

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)


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
{answers}

Requirements:

- Answer the user's question directly.
- Integrate all relevant information into one coherent response.
- Do NOT mention specialist agents, tools, workflows, prompts, planning, or internal reasoning.
- Do NOT say things like "As the Reviewer Agent", "According to the workflow", or "Based on the agent outputs".
- Respond naturally, as if a single intelligent assistant is answering.
- If there are multiple pieces of information, organize them clearly.
- If the information is insufficient, say so honestly.
"""

    response = client.chat.completions.create(
        model="deepseek-v4-flash",
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0
    )

    return response.choices[0].message.content