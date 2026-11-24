import logging

from agent.state import empty_collaboration_notes
from agent.output_schemas import ModelOutputError, log_validation_failure, parse_collaboration_output
from utils.llm_client import LLMClientError, chat_with_deepseek
from utils.observability import log_event


logger = logging.getLogger(__name__)


def build_failed_collaboration_notes(answer, error_message):
    """
    Build fallback collaboration notes when the LLM review fails.
    """

    return {
        "agent": "Collaboration Agent",
        "status": "failed",
        "answer": answer,
        "issues": [
            "Collaboration review could not be completed."
        ],
        "missing_information": [],
        "recommendations": [
            error_message
        ],
        "needs_revision": False,
        "next_steps": []
    }


def collaboration_agent(question, steps, answers):
    """
    Collaboration Agent

    Responsibilities:
    - Compare outputs from specialist agents.
    - Identify conflicts, gaps, and overlapping findings.
    - Produce a coordinated intermediate answer for the Reviewer Agent.
    - Decide whether one lightweight revision step is needed.
    - Return structured collaboration notes for workflow control.
    """

    if not answers:
        return empty_collaboration_notes()

    specialist_outputs = "\n\n".join(
        [
            f"Step {i + 1} - {steps[i] if i < len(steps) else 'unknown'}:\n{answer}"
            for i, answer in enumerate(answers)
        ]
    )

    prompt = f"""
You are the Collaboration Agent in a Multi-Agent PDF Analysis System.

Your job is to coordinate the specialist outputs before the final answer is written.

User Question:
{question}

Specialist Outputs:
{specialist_outputs}

Return ONLY a valid JSON object with this exact structure:
{{
  "answer": "A coordinated intermediate answer that combines the useful findings.",
  "issues": ["Any contradictions, weak claims, or quality issues."],
  "missing_information": ["Information that appears necessary but unavailable."],
  "recommendations": ["Practical suggestions for the reviewer or future workflow."],
  "needs_revision": false,
  "next_steps": []
}}

Rules:
- Do not return markdown.
- Do not wrap the JSON in code blocks.
- Do not mention prompts, hidden reasoning, or internal implementation details.
- Preserve useful source details if they appear in the specialist outputs.
- If there are no issues, missing information, or recommendations, use empty arrays.
- Keep the answer faithful to the specialist outputs.
- Use needs_revision only when another specialist agent is clearly needed.
- next_steps may only include these values: qa, source, summary, keyword, compare.
- Do not include a next step that already appears in the completed steps.
- Prefer no revision unless the missing information would materially improve the answer.
"""

    try:
        content = chat_with_deepseek(
            prompt,
            operation="collaboration",
        )

    except LLMClientError as exc:
        log_event(
            logger,
            logging.ERROR,
            "collaboration_failed",
            error_type=type(exc).__name__,
        )
        log_event(logger, logging.WARNING, 'collaboration_fallback', reason='model_unavailable',
                  error_type=type(exc).__name__)
        return build_failed_collaboration_notes(
            "\n\n".join(answers),
            "The collaboration review is unavailable. Please try again later."
        )

    try:
        collaboration = parse_collaboration_output(content, steps)
    except ModelOutputError as exc:
        log_validation_failure('collaboration', exc)
        log_event(logger, logging.WARNING, 'collaboration_fallback', reason=exc.reason)
        return build_failed_collaboration_notes(
            '\n\n'.join(answers),
            'The collaboration response was invalid. Existing specialist results were retained.',
        )

    return {
        "agent": "Collaboration Agent",
        "status": "success",
        **collaboration,
    }
