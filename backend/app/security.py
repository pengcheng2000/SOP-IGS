from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from .models import utcnow

password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def new_session(ttl_hours: int) -> tuple[str, str, str, object]:
    token = secrets.token_urlsafe(48)
    csrf = secrets.token_urlsafe(32)
    return token, token_digest(token), csrf, utcnow() + timedelta(hours=ttl_hours)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

