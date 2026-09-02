import os
import logging
from time import perf_counter

from dotenv import load_dotenv
from openai import OpenAI

from utils.observability import log_event, record_llm_usage


load_dotenv()

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"
DEFAULT_TIMEOUT = 60

_deepseek_client = None
logger = logging.getLogger(__name__)


class LLMClientError(Exception):
    """
    Raised when a DeepSeek chat completion cannot be completed.
    """


def get_deepseek_model():
    """
    Return the configured DeepSeek model name.
    """

    return os.getenv("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL)


def get_deepseek_client():
    """
    Return a shared DeepSeek-compatible OpenAI client.
    """

    global _deepseek_client

    if _deepseek_client is None:
        api_key = os.getenv("DEEPSEEK_API_KEY")

        if not api_key:
            raise LLMClientError(
                "DEEPSEEK_API_KEY is not configured."
            )

        _deepseek_client = OpenAI(
            api_key=api_key,
            base_url=DEEPSEEK_BASE_URL,
            timeout=DEFAULT_TIMEOUT
        )

    return _deepseek_client


def chat_with_deepseek(
    prompt,
    model=None,
    temperature=0,
    operation="unspecified",
):
    """
    Send a single prompt to DeepSeek and return the response text.
    """

    requested_model = model or get_deepseek_model()
    started_at = perf_counter()

    try:
        response = get_deepseek_client().chat.completions.create(
            model=requested_model,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=temperature
        )

    except LLMClientError:
        raise

    except Exception as exc:
        log_event(
            logger,
            logging.ERROR,
            "llm_call_failed",
            model=requested_model,
            operation=operation,
            duration_ms=round((perf_counter() - started_at) * 1000, 2),
            error_type=type(exc).__name__,
        )
        raise LLMClientError(
            f"DeepSeek request failed: {exc}"
        ) from exc

    duration_ms = (perf_counter() - started_at) * 1000
    response_model = getattr(response, "model", None) or requested_model
    usage = record_llm_usage(
        response_model,
        operation,
        getattr(response, "usage", None),
        duration_ms,
    )
    log_event(
        logger,
        logging.INFO,
        "llm_call_completed",
        **usage,
    )

    try:
        return response.choices[0].message.content

    except (AttributeError, IndexError, TypeError) as exc:
        log_event(
            logger,
            logging.ERROR,
            "llm_response_invalid",
            model=response_model,
            operation=operation,
            error_type=type(exc).__name__,
        )
        raise LLMClientError(
            "DeepSeek returned an invalid response format."
        ) from exc
