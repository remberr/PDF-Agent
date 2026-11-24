"""Per-process input limits and fail-fast upload admission; no background queue."""
import asyncio
import os
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, fields
from functools import lru_cache

from fastapi import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


@dataclass(frozen=True)
class InputLimits:
    max_question_chars: int = 8000
    max_files: int = 5
    max_file_bytes: int = 20 * 1024 * 1024
    max_batch_bytes: int = 40 * 1024 * 1024
    max_pages: int = 200
    max_text_chars: int = 1_000_000
    max_chunks: int = 2000
    max_concurrent_uploads: int = 1
    max_concurrent_questions: int = 2
    body_idle_seconds: int = 15
    max_body_seconds: int = 120

    @property
    def max_upload_body_bytes(self) -> int:
        # Includes bounded multipart headers/boundaries, not only file contents.
        return self.max_batch_bytes + 64 * 1024

    @property
    def max_question_body_bytes(self) -> int:
        # One non-BMP character may use two six-byte JSON Unicode escapes.
        return self.max_question_chars * 12 + 4096


LIMIT_ENV_VARS = {
    'max_question_chars': 'PDF_AGENT_MAX_QUESTION_CHARS',
    'max_files': 'PDF_AGENT_MAX_UPLOAD_FILES',
    'max_file_bytes': 'PDF_AGENT_MAX_FILE_BYTES',
    'max_batch_bytes': 'PDF_AGENT_MAX_BATCH_BYTES',
    'max_pages': 'PDF_AGENT_MAX_PDF_PAGES',
    'max_text_chars': 'PDF_AGENT_MAX_PDF_TEXT_CHARS',
    'max_chunks': 'PDF_AGENT_MAX_PDF_CHUNKS',
    'max_concurrent_uploads': 'PDF_AGENT_MAX_CONCURRENT_UPLOADS',
    'max_concurrent_questions': 'PDF_AGENT_MAX_CONCURRENT_QUESTIONS',
    'body_idle_seconds': 'PDF_AGENT_BODY_IDLE_SECONDS',
    'max_body_seconds': 'PDF_AGENT_BODY_TIMEOUT_SECONDS',
}


def load_input_limits(environ: Mapping[str, str] | None = None) -> InputLimits:
    env = os.environ if environ is None else environ
    defaults = InputLimits()
    values = {}
    for field in fields(defaults):
        name = LIMIT_ENV_VARS[field.name]
        try:
            value = int(env.get(name, str(getattr(defaults, field.name))))
            if value <= 0:
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError(f'{name} must be a positive integer.') from None
        values[field.name] = value
    return InputLimits(**values)


@lru_cache(maxsize=1)
def get_input_limits() -> InputLimits:
    return load_input_limits()


class ProcessingAdmission:
    def __init__(self, capacity: int):
        self._slots = threading.BoundedSemaphore(capacity)
        # HTTP middleware and service share one permit for the same task.
        self._admitted: ContextVar[bool] = ContextVar('upload_admitted', default=False)

    @contextmanager
    def slot(self) -> Iterator[None]:
        if self._admitted.get():
            yield
            return
        if not self._slots.acquire(blocking=False):
            raise HTTPException(429, 'Document processing is busy. Please retry later.',
                                headers={'Retry-After': '1'})
        token = self._admitted.set(True)
        try:
            yield
        finally:
            self._admitted.reset(token)
            self._slots.release()


@lru_cache(maxsize=1)
def get_upload_admission() -> ProcessingAdmission:
    return ProcessingAdmission(get_input_limits().max_concurrent_uploads)


@lru_cache(maxsize=1)
def get_question_admission() -> ProcessingAdmission:
    return ProcessingAdmission(get_input_limits().max_concurrent_questions)


class InputLimitsMiddleware:
    """Count actual bytes before FastAPI buffers JSON or spools multipart files."""
    def __init__(self, app: ASGIApp, limits: InputLimits | None = None):
        self.app = app
        self.limits = limits or get_input_limits()
        self.admission = get_upload_admission()
        self.question_admission = get_question_admission()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        parts = scope.get('path', '').strip('/').split('/')
        is_session = len(parts) >= 3 and parts[0] == 'sessions'
        upload = is_session and len(parts) == 3 and parts[2] == 'pdfs'
        question = is_session and parts[2:] in (['ask'], ['ask', 'stream'])
        if scope['type'] != 'http' or scope.get('method') != 'POST' or not (upload or question):
            await self.app(scope, receive, send)
            return
        limit = self.limits.max_upload_body_bytes if upload else self.limits.max_question_body_bytes
        received = 0
        started = False
        body_finished = False
        deadline = asyncio.get_running_loop().time() + self.limits.max_body_seconds

        async def bounded_receive() -> Message:
            nonlocal received, body_finished
            if body_finished:
                # SSE uses receive again to listen for disconnects. A completed
                # request body must not impose a timeout on model generation.
                return await receive()
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise HTTPException(408, 'Request body timed out.')
            try:
                message = await asyncio.wait_for(receive(), timeout=min(
                    self.limits.body_idle_seconds, remaining))
            except TimeoutError:
                raise HTTPException(408, 'Request body timed out.') from None
            if message['type'] == 'http.request':
                received += len(message.get('body', b''))
                if received > limit:
                    raise HTTPException(413, 'Request body exceeds the configured limit.')
                body_finished = not message.get('more_body', False)
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal started
            if message['type'] == 'http.response.start':
                started = True
            await send(message)

        try:
            admission = self.admission if upload else self.question_admission
            with admission.slot():
                for name, value in scope.get('headers', []):
                    if name.lower() == b'content-length':
                        try:
                            declared = int(value)
                            if declared < 0:
                                raise ValueError
                        except ValueError:
                            raise HTTPException(400, 'Invalid Content-Length.') from None
                        if declared > limit:
                            raise HTTPException(413, 'Request body exceeds the configured limit.')
                await self.app(scope, bounded_receive, tracked_send)
        except HTTPException as exc:
            if started:
                raise
            await JSONResponse({'detail': exc.detail}, status_code=exc.status_code,
                               headers=exc.headers)(scope, receive, send)
