"""Credential fixtures for existing tests focused on downstream HTTP behavior."""
from unittest.mock import patch

from app.services.session_credentials import issue_credential

HTTP_SESSION_ID = 'a' * 32
AUTH_HEADERS = {'Authorization': 'Bearer ' + 'A' * 43}
BROWSER_HEADERS = {'Origin': 'https://localhost:5173', 'X-PDF-Agent-Client': 'browser'}


def accept_test_owner():
    return patch('app.api.session_access.check_session_owner', return_value=True)


def create_bearer_session(store):
    token, owner = issue_credential('bearer')
    sid, _ = store.create_owned_session(owner)
    return sid, {'Authorization': f'Bearer {token}'}
