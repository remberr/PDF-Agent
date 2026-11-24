"""Opaque per-session owner credentials."""
import base64
import hashlib
import re
import secrets
from dataclasses import dataclass
from typing import Literal


OWNER_LIFETIME_SECONDS = 24 * 60 * 60
SESSION_ID = re.compile(r'[a-f0-9]{32}')
TOKEN = re.compile(r'[A-Za-z0-9_-]{43}')
OwnerMode = Literal['cookie', 'bearer']


@dataclass(frozen=True, repr=False)
class OwnerCredential:
    mode: OwnerMode
    digest: bytes


def issue_credential(mode: OwnerMode) -> tuple[str, OwnerCredential]:
    raw = secrets.token_bytes(32)
    token = base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')
    return token, OwnerCredential(mode, hashlib.sha256(raw).digest())


def parse_credential(token: str, mode: OwnerMode) -> OwnerCredential | None:
    if not TOKEN.fullmatch(token):
        return None
    raw = base64.urlsafe_b64decode(token + '=')
    if base64.urlsafe_b64encode(raw).decode('ascii') != token + '=':
        return None
    return OwnerCredential(mode, hashlib.sha256(raw).digest())
