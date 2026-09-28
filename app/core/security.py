"""Пароли (scrypt из стандартной библиотеки) и токены входа (JWT)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

import jwt

_N, _R, _P = 2**14, 8, 1
JWT_ALG = "HS256"


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_b64, digest_b64 = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    salt, digest = base64.b64decode(salt_b64), base64.b64decode(digest_b64)
    probe = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=len(digest))
    return hmac.compare_digest(probe, digest)


def create_token(user_id: str, secret: str, ttl_hours: int) -> str:
    now = datetime.now(UTC)
    payload = {"sub": user_id, "iat": now, "exp": now + timedelta(hours=ttl_hours)}
    return jwt.encode(payload, secret, algorithm=JWT_ALG)


def read_token(token: str, secret: str) -> str | None:
    """id пользователя или None, если токен неверен или истёк."""
    try:
        payload = jwt.decode(token, secret, algorithms=[JWT_ALG])
    except jwt.PyJWTError:
        return None
    sub = payload.get("sub")
    return sub if isinstance(sub, str) else None
