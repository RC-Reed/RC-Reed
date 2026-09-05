"""Password hashing, JWT issuance, and the encrypted credential vault.

Design notes:
  * Passwords: Argon2id via passlib. Never reversible.
  * Connector credentials: Fernet (AES-128-CBC + HMAC) with a key that lives
    outside the database, so a stolen DB dump alone yields no usable secrets.
  * Tokens: short-lived HS256 JWTs. There is no refresh-token dance yet;
    a 12h access token matches a personal, single-operator system.
"""

from __future__ import annotations

import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings

ALGORITHM = "HS256"
_pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


# --------------------------------------------------------------------------
# Passwords
# --------------------------------------------------------------------------
def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _pwd_context.verify(password, hashed)
    except ValueError:
        return False


# --------------------------------------------------------------------------
# Tokens
# --------------------------------------------------------------------------
def create_access_token(subject: str, extra: dict[str, Any] | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_ttl_minutes)).timestamp()),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except JWTError:
        return None


# --------------------------------------------------------------------------
# Credential vault
# --------------------------------------------------------------------------
def _fernet() -> Fernet:
    return Fernet(settings.vault_key.encode() if isinstance(settings.vault_key, str) else settings.vault_key)


def encrypt_secrets(payload: dict[str, Any]) -> str:
    """Encrypt a connector's secret bundle into a single opaque string."""
    return _fernet().encrypt(json.dumps(payload).encode()).decode()


def decrypt_secrets(blob: str | None) -> dict[str, Any]:
    """Decrypt a bundle. Returns {} when absent or when the key no longer matches."""
    if not blob:
        return {}
    try:
        return json.loads(_fernet().decrypt(blob.encode()).decode())
    except (InvalidToken, ValueError):
        return {}


def redact(payload: dict[str, Any]) -> dict[str, Any]:
    """Shape-preserving redaction for API responses and logs."""
    return {key: ("••••" + str(value)[-4:] if value else "") for key, value in payload.items()}


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
