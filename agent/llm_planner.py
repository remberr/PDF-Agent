import json

from utils.llm_client import LLMClientError, chat_with_deepseek


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

    try:
        content = chat_with_deepseek(prompt).strip()

    except LLMClientError:
        return ["qa"]

    try:
        steps = json.loads(content)

    except json.JSONDecodeError:
        steps = ["qa"]

    if not isinstance(steps, list):
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
