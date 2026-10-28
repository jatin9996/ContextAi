import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import LANGUAGES, RESPONSE_STYLES
from app.core.errors import AppError
from app.core.security import (
    dummy_password_hash,
    expiry,
    hash_password,
    hash_token,
    new_token,
    validate_password,
    verify_password,
)
from app.core.time import utcnow
from app.models import AuthToken, Session, User
from app.services.audit import record_audit

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover
    ZoneInfo = None
    ZoneInfoNotFoundError = Exception


@dataclass
class AuthResult:
    user: User
    token: str
    dev_token: str | None = None


async def register_user(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    display_name: str,
    user_agent: str | None,
    ip_address: str | None,
) -> AuthResult:
    validate_password(password)
    normalized = email.strip().lower()
    existing = await session.scalar(select(User).where(User.email == normalized))
    if existing is not None:
        raise AppError("account_exists", "An account with this email already exists.", 409)
    name = display_name.strip()
    if not name:
        raise AppError("invalid_profile", "Display name cannot be empty.")
    user = User(
        email=normalized,
        password_hash=hash_password(password),
        display_name=name[:80],
    )
    session.add(user)
    await session.flush()
    dev_token = await _issue_token(session, user.id, "email_verify", hours=settings.email_verify_ttl_hours)
    token = await _create_session(session, user, user_agent, ip_address)
    await record_audit(session, user_id=user.id, action="register", resource_type="user", resource_id=user.id)
    return AuthResult(user=user, token=token, dev_token=dev_token)


async def login_user(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    user_agent: str | None,
    ip_address: str | None,
) -> AuthResult:
    user = await session.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None:
        verify_password(password, dummy_password_hash())
        raise AppError("invalid_credentials", "Invalid email or password.", 401)
    if not verify_password(password, user.password_hash):
        raise AppError("invalid_credentials", "Invalid email or password.", 401)
    if settings.require_verified_email and user.email_verified_at is None:
        raise AppError("email_unverified", "Verify your email before signing in.", 403)
    token = await _create_session(session, user, user_agent, ip_address)
    await record_audit(session, user_id=user.id, action="login", resource_type="user", resource_id=user.id)
    return AuthResult(user=user, token=token)


async def logout_user(session: AsyncSession, session_id: uuid.UUID) -> None:
    await session.execute(delete(Session).where(Session.id == session_id))


async def request_password_reset(session: AsyncSession, email: str) -> str | None:
    user = await session.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None:
        return None
    return await _issue_token(session, user.id, "password_reset", minutes=settings.password_reset_ttl_minutes)


async def reset_password(session: AsyncSession, token: str, password: str) -> None:
    validate_password(password)
    auth_token = await _consume_token(session, token, "password_reset")
    user = await session.get(User, auth_token.user_id)
    if user is None:
        raise AppError("invalid_token", "This reset link is invalid.", 400)
    user.password_hash = hash_password(password)
    user.updated_at = utcnow()
    await session.execute(delete(Session).where(Session.user_id == user.id))


async def change_password(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    current_password: str,
    new_password: str,
) -> None:
    validate_password(new_password)
    user = await session.get(User, user_id)
    if user is None or not verify_password(current_password, user.password_hash):
        raise AppError("invalid_credentials", "The current password is incorrect.", 401)
    user.password_hash = hash_password(new_password)
    user.updated_at = utcnow()
    await session.execute(delete(Session).where(Session.user_id == user.id, Session.id != session_id))


async def request_verification(session: AsyncSession, user_id: uuid.UUID) -> str | None:
    return await _issue_token(session, user_id, "email_verify", hours=settings.email_verify_ttl_hours)


async def verify_email(session: AsyncSession, token: str) -> None:
    auth_token = await _consume_token(session, token, "email_verify")
    user = await session.get(User, auth_token.user_id)
    if user is None:
        raise AppError("invalid_token", "This verification link is invalid.", 400)
    user.email_verified_at = utcnow()
    user.updated_at = utcnow()


async def update_profile(session: AsyncSession, user_id: uuid.UUID, changes: dict) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise AppError("unauthorized", "Authentication is required.", 401)
    if "display_name" in changes and changes["display_name"] is not None:
        name = changes["display_name"].strip()
        if not name:
            raise AppError("invalid_profile", "Display name cannot be empty.")
        user.display_name = name[:80]
    if "timezone" in changes and changes["timezone"] is not None:
        _validate_timezone(changes["timezone"])
        user.timezone = changes["timezone"]
    if "preferred_language" in changes and changes["preferred_language"] is not None:
        if changes["preferred_language"] not in LANGUAGES:
            raise AppError("invalid_profile", "Choose a supported language.")
        user.preferred_language = changes["preferred_language"]
    if "response_style" in changes and changes["response_style"] is not None:
        if changes["response_style"] not in RESPONSE_STYLES:
            raise AppError("invalid_profile", "Choose concise, balanced, or detailed.")
        user.response_style = changes["response_style"]
    if "memory_enabled" in changes and changes["memory_enabled"] is not None:
        user.memory_enabled = bool(changes["memory_enabled"])
    user.updated_at = utcnow()
    await session.flush()
    return user


async def _create_session(session: AsyncSession, user: User, user_agent: str | None, ip_address: str | None) -> str:
    raw = new_token()
    row = Session(
        user_id=user.id,
        token_hash=hash_token(raw),
        expires_at=expiry(hours=settings.session_ttl_hours),
        user_agent=(user_agent or "")[:300] or None,
        ip_address=(ip_address or "")[:64] or None,
    )
    session.add(row)
    await session.flush()
    stale = list(
        await session.scalars(
            select(Session.id)
            .where(Session.user_id == user.id)
            .order_by(Session.created_at.desc())
            .offset(settings.max_sessions_per_user)
        )
    )
    if stale:
        await session.execute(delete(Session).where(Session.id.in_(stale)))
    return raw


async def _issue_token(session: AsyncSession, user_id: uuid.UUID, purpose: str, *, hours: int = 0, minutes: int = 0) -> str:
    raw = new_token()
    session.add(
        AuthToken(
            user_id=user_id,
            purpose=purpose,
            token_hash=hash_token(raw),
            expires_at=expiry(hours=hours, minutes=minutes),
        )
    )
    await session.flush()
    return raw


async def _consume_token(session: AsyncSession, raw: str, purpose: str) -> AuthToken:
    auth_token = await session.scalar(
        select(AuthToken).where(AuthToken.token_hash == hash_token(raw), AuthToken.purpose == purpose)
    )
    if auth_token is None or auth_token.used_at is not None or auth_token.expires_at < utcnow():
        raise AppError("invalid_token", "This link is invalid or has expired.", 400)
    auth_token.used_at = utcnow()
    await session.flush()
    return auth_token


def _validate_timezone(value: str) -> None:
    if ZoneInfo is None:
        return
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise AppError("invalid_profile", "Choose a valid timezone.") from exc
