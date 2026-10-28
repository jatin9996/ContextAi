import uuid
from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.core.rate_limit import limiter
from app.core.security import hash_token
from app.core.time import utcnow
from app.db.session import get_session
from app.models import Session, User


@dataclass
class CurrentUser:
    id: uuid.UUID
    session_id: uuid.UUID
    email: str
    display_name: str
    timezone: str
    preferred_language: str
    response_style: str
    memory_enabled: bool
    email_verified: bool


def client_ip(request: Request) -> str:
    if settings.trust_proxy:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()[:64]
    if request.client and request.client.host:
        return request.client.host[:64]
    return "unknown"


def enforce_rate(key: str, *, limit: int, window_seconds: float) -> None:
    if settings.rate_limit_enabled:
        limiter.check(key, limit=limit, window_seconds=window_seconds)


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> CurrentUser:
    raw = request.cookies.get(settings.cookie_name)
    if not raw:
        raise AppError("unauthorized", "Authentication is required.", 401)
    row = await session.scalar(select(Session).where(Session.token_hash == hash_token(raw)))
    if row is None or row.revoked_at is not None:
        raise AppError("unauthorized", "Authentication is required.", 401)
    if row.expires_at < utcnow():
        raise AppError("session_expired", "Your session has expired.", 401)
    user = await session.get(User, row.user_id)
    if user is None:
        raise AppError("unauthorized", "Authentication is required.", 401)
    return CurrentUser(
        id=user.id,
        session_id=row.id,
        email=user.email,
        display_name=user.display_name,
        timezone=user.timezone,
        preferred_language=user.preferred_language,
        response_style=user.response_style,
        memory_enabled=user.memory_enabled,
        email_verified=user.email_verified_at is not None,
    )


def require_user(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    return user
