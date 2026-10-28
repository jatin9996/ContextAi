import hashlib
import re
import secrets
from datetime import timedelta

import bcrypt

from app.core.errors import AppError
from app.core.time import utcnow

_MIN_PASSWORD = 10
_MAX_PASSWORD = 64
_DUMMY_HASH: str | None = None


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def dummy_password_hash() -> str:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password("timing-placeholder-password")
    return _DUMMY_HASH


def validate_password(password: str) -> None:
    if not isinstance(password, str) or not (_MIN_PASSWORD <= len(password) <= _MAX_PASSWORD):
        raise AppError(
            "weak_password",
            "Use 10 to 64 characters with an uppercase letter, a lowercase letter, and a digit.",
        )
    if len(password.encode("utf-8")) > 72:
        raise AppError("weak_password", "Password is too long for the password hasher.")
    if not re.search(r"[a-z]", password) or not re.search(r"[A-Z]", password) or not re.search(r"\d", password):
        raise AppError(
            "weak_password",
            "Use 10 to 64 characters with an uppercase letter, a lowercase letter, and a digit.",
        )


def expiry(minutes: int = 0, hours: int = 0):
    return utcnow() + timedelta(minutes=minutes, hours=hours)


def email_fingerprint(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()
