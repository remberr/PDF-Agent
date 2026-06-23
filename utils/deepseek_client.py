import os
from dotenv import load_dotenv
from openai import OpenAI

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

    history_text = ""

    if chat_history:
        for message in chat_history:
            role = message["role"]
            content = message["content"]
            history_text += f"{role}: {content}\n"

    prompt = f"""
You are a helpful PDF assistant.

You have two information sources:
1. Chat History
2. PDF Content

Rules:
- If the user asks about the conversation itself, such as previous questions, first question, last question, or chat history, answer using Chat History.
- If the user asks about the PDF, answer based ONLY on the PDF Content.
- Use Chat History only to understand follow-up questions.
- If the answer cannot be found in the PDF Content or Chat History, say the information is not available.

Chat History:
{history_text}

PDF Content:
{context}

Current Question:
{question}
"""

    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0
    )

    return response.choices[0].message.content