"""Access checks for session routes, before framework body parsing."""
import os
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.services.postgres_store import check_session_owner
from app.services.session_credentials import (
    OWNER_LIFETIME_SECONDS, SESSION_ID, OwnerCredential, OwnerMode, parse_credential,
)


COOKIE_NAME = '__Secure-pdf-agent-owner'
NO_STORE = {'Cache-Control': 'no-store'}
DEFAULT_ORIGINS = (
    'https://127.0.0.1:5173,https://localhost:5173,'
    'https://127.0.0.1:8000,https://localhost:8000'
)


def not_found() -> HTTPException:
    return HTTPException(404, 'Session not found.', headers=NO_STORE)


def forbidden() -> HTTPException:
    return HTTPException(403, 'Session request origin is not allowed.', headers=NO_STORE)


def _browser_request(request: Request, *, origin_required: bool) -> None:
    if request.headers.getlist('x-pdf-agent-client') != ['browser']:
        raise forbidden()
    origins = request.headers.getlist('origin')
    if not origins and not origin_required:
        return
    allowed = {origin.strip() for origin in
               os.getenv('SESSION_BROWSER_ORIGINS', DEFAULT_ORIGINS).split(',')}
    if len(origins) != 1 or origins[0] not in allowed:
        raise forbidden()
    origin = urlsplit(origins[0])
    if origin.scheme != 'https' or not origin.hostname or origin.username is not None or (
        origin.path or origin.query or origin.fragment
    ):
        raise forbidden()


def creation_mode(request: Request) -> OwnerMode:
    modes = request.headers.getlist('x-session-mode')
    if modes == ['bearer']:
        if request.headers.getlist('origin') or request.headers.getlist('authorization'):
            raise forbidden()
        return 'bearer'
    if modes or request.headers.getlist('authorization'):
        raise forbidden()
    _browser_request(request, origin_required=True)
    return 'cookie'


def _owner_from_request(request: Request) -> OwnerCredential:
    cookies = []
    for header in request.headers.getlist('cookie'):
        for pair in header.split(';'):
            name, _, value = pair.strip().partition('=')
            if name == COOKIE_NAME:
                cookies.append(value)
    authorization = request.headers.getlist('authorization')
    owner = None
    if len(authorization) == 1 and not cookies:
        scheme, _, token = authorization[0].partition(' ')
        if scheme.lower() == 'bearer':
            owner = parse_credential(token, 'bearer')
    if len(cookies) == 1 and not authorization:
        owner = parse_credential(cookies[0], 'cookie')
    if owner is None:
        raise not_found()
    if owner.mode == 'cookie':
        _browser_request(request, origin_required=request.method != 'GET')
    return owner


def set_owner_cookie(response: Response, sid: str, token: str) -> None:
    response.set_cookie(COOKIE_NAME, token, max_age=OWNER_LIFETIME_SECONDS, secure=True,
                        httponly=True, samesite='strict', path=f'/sessions/{sid}')


def clear_owner_cookie(response: Response, sid: str) -> None:
    response.delete_cookie(COOKIE_NAME, secure=True, httponly=True, samesite='strict',
                           path=f'/sessions/{sid}')


class SessionRoute(APIRoute):
    def get_route_handler(self):
        endpoint = super().get_route_handler()

        async def handle(request: Request) -> Response:
            try:
                sid = request.path_params.get('session_id')
                if sid is not None:
                    if not SESSION_ID.fullmatch(sid):
                        raise not_found()
                    owner = _owner_from_request(request)
                    if not await run_in_threadpool(check_session_owner, sid, owner):
                        raise not_found()
                    request.state.session_owner = owner
                response = await endpoint(request)
            except RequestValidationError as exc:
                # Pydantic's default response serializes the rejected input.
                raise HTTPException(422, 'Invalid session request.', headers=NO_STORE) from exc
            except SQLAlchemyError as exc:
                raise HTTPException(503, 'Session storage is temporarily unavailable.',
                                    headers=NO_STORE) from exc
            except HTTPException as exc:
                exc.headers = {**(exc.headers or {}), **NO_STORE}
                raise
            response.headers.update(NO_STORE)
            return response

        return handle
