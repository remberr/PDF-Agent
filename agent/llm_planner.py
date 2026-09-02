import json
import re

from utils.llm_client import LLMClientError, chat_with_deepseek


INTENT_KEYWORDS = {
    "summary": (
        "summarize",
        "summary",
        "summaries",
        "overview",
        "synopsis",
        "总结",
        "概括",
        "摘要",
    ),
    "keyword": (
        "keyword",
        "keywords",
        "key concept",
        "key concepts",
        "terminology",
        "关键词",
        "关键概念",
        "术语",
    ),
    "compare": (
        "compare",
        "comparison",
        "comparisons",
        "difference",
        "differences",
        "similarity",
        "similarities",
        "versus",
        " vs ",
        "比较",
        "对比",
        "区别",
        "差异",
        "异同",
    ),
    "source": (
        "source",
        "sources",
        "citation",
        "citations",
        "evidence",
        "reference",
        "references",
        "page number",
        "page numbers",
        "来源",
        "引用",
        "证据",
        "参考文献",
        "页码",
        "出处",
    ),
}

QUESTION_PREFIXES = (
    "what ",
    "why ",
    "how ",
    "when ",
    "where ",
    "who ",
    "which ",
    "is ",
    "are ",
    "do ",
    "does ",
    "can ",
    "could ",
    "explain ",
    "describe ",
    "tell me ",
)

CHINESE_QUESTION_MARKERS = (
    "什么",
    "为什么",
    "为何",
    "如何",
    "怎么",
    "是否",
    "哪个",
    "哪些",
    "哪里",
    "谁",
    "解释",
    "说明",
    "介绍",
    "请问",
)


def _first_keyword_position(text, keywords):
    positions = []

    for keyword in keywords:
        if keyword.isascii():
            pattern = rf"(?<!\w){re.escape(keyword.strip())}(?!\w)"
            match = re.search(pattern, text)
            position = match.start() if match else -1
        else:
            position = text.find(keyword)

        if position >= 0:
            positions.append(position)

    return min(positions) if positions else None


def _looks_like_question(text):
    return (
        "?" in text
        or "？" in text
        or text.startswith(QUESTION_PREFIXES)
        or any(marker in text for marker in CHINESE_QUESTION_MARKERS)
    )


def plan_steps_fast(question):
    """
    Return deterministic steps for clear user intents.

    None means the request is ambiguous enough to use the LLM planner.
    """

    text = " ".join(question.casefold().split())
    matches = []

    for step, keywords in INTENT_KEYWORDS.items():
        position = _first_keyword_position(text, keywords)
        if position is not None:
            matches.append((position, step))

    matches.sort(key=lambda match: match[0])
    matched_steps = [step for _, step in matches]
    content_steps = [step for step in matched_steps if step != "source"]
    source_requested = "source" in matched_steps

    if content_steps:
        if source_requested:
            content_steps.append("source")
        return content_steps

    if source_requested:
        if _looks_like_question(text):
            return ["qa", "source"]
        return ["source"]

    if _looks_like_question(text):
        return ["qa"]

    return None


def plan_steps_with_llm(question):
    """
    Planner Agent

    Responsibilities:
    - Understand the user's request.
    - Decide which specialist agents should collaborate.
    - Return an ordered list of agent steps.
    """

    fast_steps = plan_steps_fast(question)
    if fast_steps is not None:
        return fast_steps

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
