"""Strict boundaries for model-generated control data, not natural-language answers."""
import json
import logging
import re
from typing import Annotated

from pydantic import (
    AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, RootModel,
    StrictBool, StringConstraints, ValidationError, ValidationInfo,
    field_validator, model_validator,
)
from pydantic_core import PydanticCustomError

from agent.state import SpecialistStep
from utils.observability import log_event


MAX_PLANNER_CHARS = 2048
MAX_COLLABORATION_CHARS = 32768
MAX_STEPS = 5
logger = logging.getLogger(__name__)


def _trim_step(value):
    return value.strip() if isinstance(value, str) else value


def _unicode_text(value: str) -> str:
    try:
        value.encode('utf-8')
    except UnicodeError:
        raise PydanticCustomError('invalid_unicode', 'Text must be valid Unicode.') from None
    return value


Step = Annotated[SpecialistStep, BeforeValidator(_trim_step)]
StepList = Annotated[list[Step], Field(max_length=MAX_STEPS)]
AnswerText = Annotated[str, StringConstraints(strict=True, strip_whitespace=True,
    min_length=1, max_length=16000), AfterValidator(_unicode_text)]
NoteText = Annotated[str, StringConstraints(strict=True, strip_whitespace=True,
    min_length=1, max_length=2048), AfterValidator(_unicode_text)]
NoteList = Annotated[list[NoteText], Field(max_length=20)]


class PlannerPlan(RootModel[Annotated[list[Step], Field(min_length=1, max_length=MAX_STEPS)]]):
    model_config = ConfigDict(strict=True)

    @field_validator('root')
    @classmethod
    def unique_steps(cls, steps):
        return list(dict.fromkeys(steps))


class CollaborationOutput(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')

    answer: AnswerText
    issues: NoteList
    missing_information: NoteList
    recommendations: NoteList
    needs_revision: StrictBool
    next_steps: StepList

    @field_validator('next_steps')
    @classmethod
    def unique_steps(cls, steps):
        return list(dict.fromkeys(steps))

    @model_validator(mode='after')
    def legal_revision(self, info: ValidationInfo):
        if self.needs_revision != bool(self.next_steps):
            raise PydanticCustomError('revision_consistency', 'Revision flag and steps must agree.')
        completed = set((info.context or {}).get('completed_steps', ()))
        if any(step in completed for step in self.next_steps):
            raise PydanticCustomError('revision_scope', 'Revision may request only unexecuted specialists.')
        return self


class ModelOutputError(ValueError):
    """Safe reason codes only; no model response or ValidationError input values."""
    def __init__(self, reason: str, error_codes=()):
        super().__init__(reason)
        self.reason = reason
        self.error_codes = tuple(error_codes)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ModelOutputError('duplicate_keys')
        result[key] = value
    return result


def _invalid_constant(_value):
    raise ModelOutputError('non_json_constant')


def _decode(raw: str, limit: int):
    if not isinstance(raw, str):
        raise ModelOutputError('output_type')
    if len(raw) > limit:
        raise ModelOutputError('output_length')
    repairs = []
    content = raw.strip()
    if content != raw:
        repairs.append('outer_whitespace')
    if content.startswith('\ufeff'):
        content = content[1:].strip()
        repairs.append('bom')
    fence = re.fullmatch(r'```(?:json)?[ \t]*\r?\n(.*?)\r?\n```', content,
                         flags=re.DOTALL | re.IGNORECASE)
    if fence:
        content = fence.group(1).strip()
        repairs.append('json_fence')
    try:
        parsed = json.loads(content, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    except ModelOutputError:
        raise
    except (ValueError, RecursionError, UnicodeError):
        raise ModelOutputError('invalid_json') from None
    return parsed, repairs


def _schema_error(exc: ValidationError) -> ModelOutputError:
    # Error locations and context can themselves contain untrusted keys/content.
    codes = sorted({error['type'] for error in exc.errors(
        include_input=False, include_context=False, include_url=False)})
    return ModelOutputError('schema_validation', codes)


def _step_repairs(before, after) -> list[str]:
    repairs = []
    if any(step != step.strip() for step in before):
        repairs.append('step_whitespace')
    if len(before) != len(after):
        repairs.append('duplicate_steps')
    return repairs


def _log_repairs(node: str, repairs: list[str]) -> None:
    if repairs:
        log_event(logger, logging.INFO, 'model_output_repaired', node=node, repairs=repairs)


def parse_planner_output(raw: str) -> list[SpecialistStep]:
    parsed, repairs = _decode(raw, MAX_PLANNER_CHARS)
    try:
        plan = PlannerPlan.model_validate(parsed)
    except ValidationError as exc:
        raise _schema_error(exc) from None
    _log_repairs('planner', repairs + _step_repairs(parsed, plan.root))
    return plan.root


def parse_collaboration_output(raw: str, completed_steps: list[SpecialistStep]) -> dict:
    parsed, repairs = _decode(raw, MAX_COLLABORATION_CHARS)
    try:
        result = CollaborationOutput.model_validate(parsed, context={'completed_steps': completed_steps})
    except ValidationError as exc:
        raise _schema_error(exc) from None
    repairs += _step_repairs(parsed['next_steps'], result.next_steps)
    if parsed['answer'] != result.answer or any(parsed[name] != getattr(result, name)
            for name in ('issues', 'missing_information', 'recommendations')):
        repairs.append('text_whitespace')
    _log_repairs('collaboration', repairs)
    return result.model_dump()


def log_validation_failure(node: str, exc: ModelOutputError) -> None:
    log_event(logger, logging.WARNING, 'model_output_validation_failed', node=node,
              reason=exc.reason, error_codes=list(exc.error_codes))
