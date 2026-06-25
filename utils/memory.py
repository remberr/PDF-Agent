"""
Memory Manager

Responsibilities:
- Manage recent conversation memory.
- Build conversation summary memory.
- Manage current PDF session memory.
- Provide unified memory context for all agents.
"""

import os
import hashlib
from collections import OrderedDict

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)

_memory_cache = {}


def _hash_text(text):
    return hashlib.md5(
        text.encode("utf-8")
    ).hexdigest()


def build_recent_memory(chat_history, max_messages=10):
    """
    Keep recent conversation messages.
    """

    if not chat_history:
        return "No recent conversation."

    lines = []

    for message in chat_history[-max_messages:]:

        role = message.get("role", "user").capitalize()
        content = message.get("content", "")

        if content:
            lines.append(f"{role}: {content}")

    if not lines:
        return "No recent conversation."

    return "\n".join(lines)


def build_llm_conversation_summary(chat_history, recent_window=10):
    """
    Build an LLM-generated summary from older conversation messages.
    """

    if not chat_history:
        return "No conversation summary."

    older_messages = chat_history[:-recent_window]

    if not older_messages:
        return "No older conversation to summarize."

    conversation_text = "\n".join(
        [
            f"{msg.get('role', 'user').capitalize()}: {msg.get('content', '')}"
            for msg in older_messages
            if msg.get("content", "")
        ]
    )

    if not conversation_text:
        return "No useful older conversation."

    conversation_hash = _hash_text(conversation_text)

    if conversation_hash in _memory_cache:
        return _memory_cache[conversation_hash]

    prompt = f"""
Summarize the following previous conversation for an AI PDF Agent.

Focus on:
- User goals and preferences
- Previously discussed PDFs
- Important conclusions
- Follow-up references that may be useful later
- Any unresolved tasks

Do NOT mention that this is a memory summary.
Keep it concise and factual.

Previous Conversation:
{conversation_text}
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

    summary = response.choices[0].message.content

    _memory_cache[conversation_hash] = summary

    return summary


def build_session_memory(docs):
    """
    Build memory about uploaded PDFs.
    """

    if not docs:
        return "No PDF context available."

    pdfs = OrderedDict()

    for doc in docs:

        source = doc.metadata.get("source", "Unknown PDF")
        pdfs[source] = True

    lines = ["Current uploaded PDFs:"]

    for pdf_name in pdfs.keys():
        lines.append(f"- {pdf_name}")

    return "\n".join(lines)


def build_memory(chat_history, docs):
    """
    Build complete memory for agents.
    """

    conversation_summary = build_llm_conversation_summary(
        chat_history
    )

    recent_memory = build_recent_memory(
        chat_history
    )

    session_memory = build_session_memory(
        docs
    )

    return f"""
Conversation Summary Memory:
{conversation_summary}

Recent Conversation Memory:
{recent_memory}

Session Memory:
{session_memory}
"""