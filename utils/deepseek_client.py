import os

from dotenv import load_dotenv
from openai import OpenAI

from utils.memory import build_memory

load_dotenv()

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)


def ask_deepseek(question, docs, chat_history=None):

    context = "\n\n".join(
        [
            (
                f"[PDF: {doc.metadata.get('source', 'Unknown Source')}]\n"
                f"[Page: {doc.metadata.get('page', 0) + 1}]\n"
                f"{doc.page_content}"
            )
            for doc in docs
        ]
    )

    memory = build_memory(
        chat_history,
        docs
    )

    prompt = f"""
{memory}

Relevant PDF Context:

{context}

User Question:

{question}

Requirements:
- Use conversation memory to understand follow-up questions.
- Use session memory to know which PDFs are currently involved.
- Answer only using the provided PDF context.
- If the answer is not available, say so clearly.
- Do not mention memory, agents, tools, prompts, workflows, or internal reasoning.
"""

    response = client.chat.completions.create(
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0
    )

    return response.choices[0].message.content