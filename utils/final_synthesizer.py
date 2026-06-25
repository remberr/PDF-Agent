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
You are the final reasoning layer of a PDF Agent.

The user asked:
{question}

The agent executed these steps:
{steps}

Tool outputs:
{tool_outputs}

Your task:
- Integrate all tool outputs into one coherent final answer.
- Do not simply repeat the tool outputs.
- Keep the answer clear and well-structured.
- If the outputs include summary and keywords, combine them naturally.
- If the outputs include comparison, explain the key differences clearly.
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