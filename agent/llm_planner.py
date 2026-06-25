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
    Planner Agent

    Responsibilities:
    - Understand the user's request.
    - Decide which specialist agents should collaborate.
    - Return an ordered list of agent steps.
    """

    prompt = f"""
You are the Planner Agent of a Multi-Agent PDF Analysis System.

Available specialist agents:

- qa
  Use this agent for normal PDF question answering.

- source
  Use this agent when the user asks for sources, citations,
  evidence, references, or page numbers.

- summary
  Use this agent when the user asks to summarize PDFs.

- keyword
  Use this agent when the user asks for keywords,
  key concepts, or terminology.

- compare
  Use this agent when the user asks to compare PDFs,
  explain differences, or analyze similarities.

User question:
{question}

Return ONLY a valid JSON array of agent step names.

Examples:
["qa"]
["summary"]
["summary", "keyword"]
["compare", "source"]
["compare", "summary"]

Rules:
- Return only JSON.
- Do not return markdown.
- Do not wrap the JSON in code blocks.
- Do not explain your reasoning.
- Use only these step names: qa, source, summary, keyword, compare.
- If the user asks a normal question, return ["qa"].
- If multiple tasks are requested, return multiple steps in a logical order.
"""

    response = client.chat.completions.create(
        model=os.getenv(
            "DEEPSEEK_MODEL",
            "deepseek-v4-flash"
        ),
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0
    )

    content = response.choices[0].message.content.strip()

    try:
        steps = json.loads(content)

    except json.JSONDecodeError:
        steps = ["qa"]

    allowed_agents = {
        "qa",
        "source",
        "summary",
        "keyword",
        "compare"
    }

    steps = [
        step for step in steps
        if step in allowed_agents
    ]

    if not steps:
        steps = ["qa"]

    return steps