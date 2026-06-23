import os
import json

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)


def plan_steps_with_llm(question):
    """
    Use DeepSeek to decide which tools should be used.
    """

    prompt = f"""
You are a tool planner for a PDF Agent.

Available tools:
- qa: answer questions based on PDFs
- source: find relevant source pages
- summary: summarize uploaded PDFs
- keyword: extract keywords from PDFs
- compare: compare multiple PDFs

User question:
{question}

Return ONLY a JSON array of tool names.
Example:
["summary", "keyword"]

Rules:
- If the user asks a normal question, return ["qa"].
- If the user asks to summarize, include "summary".
- If the user asks for keywords, include "keyword".
- If the user asks to compare documents, include "compare".
- If the user asks for source, page, citation, or evidence, include "source".
"""

    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "user", "content": prompt}
        ],
        temperature=0
    )

    content = response.choices[0].message.content.strip()

    try:
        steps = json.loads(content)
    except json.JSONDecodeError:
        steps = ["qa"]

    allowed_tools = {
        "qa",
        "source",
        "summary",
        "keyword",
        "compare"
    }

    steps = [
        step for step in steps
        if step in allowed_tools
    ]

    if not steps:
        steps = ["qa"]

    return steps