import os

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"
DEFAULT_TIMEOUT = 60

_deepseek_client = None


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


def chat_with_deepseek(prompt, model=None, temperature=0):
    """
    Send a single prompt to DeepSeek and return the response text.
    """

    try:
        response = get_deepseek_client().chat.completions.create(
            model=model or get_deepseek_model(),
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
        raise LLMClientError(
            f"DeepSeek request failed: {exc}"
        ) from exc

    try:
        return response.choices[0].message.content

    except (AttributeError, IndexError, TypeError) as exc:
        raise LLMClientError(
            "DeepSeek returned an invalid response format."
        ) from exc
