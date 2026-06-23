import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)


def ask_deepseek(question, docs):
    context = "\n\n".join(
        [f"Page {doc.metadata.get('page', 0) + 1}:\n{doc.page_content}" for doc in docs]
    )

    prompt = f"""
You are a helpful PDF assistant.
Answer the question based only on the following PDF content.
If the answer is not in the PDF, say you cannot find it in the document.

PDF content:
{context}

Question:
{question}
"""

    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "user", "content": prompt}
        ],
        temperature=0.2
    )

    return response.choices[0].message.content