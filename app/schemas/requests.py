from pydantic import BaseModel, Field, field_validator

from app.input_limits import get_input_limits


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1)

    @field_validator('question')
    @classmethod
    def validate_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError('Question must contain non-whitespace characters.')
        if len(value) > get_input_limits().max_question_chars:
            raise ValueError('Question exceeds the configured character limit.')
        return value
