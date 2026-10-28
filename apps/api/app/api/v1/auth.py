from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, client_ip, enforce_rate, require_user
from app.core.config import settings
from app.core.security import verify_password
from app.db.session import get_session
from app.models import User
from app.schemas.contracts import (
    ChangePasswordRequest,
    DeleteAccountRequest,
    ForgotPasswordRequest,
    LoginRequest,
    ProfileUpdate,
    RegisterRequest,
    ResetPasswordRequest,
    VerifyEmailRequest,
)
from app.serializers import user_to_dict
from app.services.deletion import delete_account
from app.services.mail import deliver_auth_email
from app.services.identity import (
    change_password,
    login_user,
    logout_user,
    register_user,
    request_password_reset,
    request_verification,
    reset_password,
    update_profile,
    verify_email,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.cookie_name,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,  # type: ignore[arg-type]
        max_age=settings.session_ttl_hours * 3600,
        path="/",
    )


@router.post("/register", status_code=201)
async def register(body: RegisterRequest, request: Request, response: Response, session: AsyncSession = Depends(get_session)):
    enforce_rate(f"register:{client_ip(request)}", limit=10, window_seconds=600)
    result = await register_user(
        session,
        email=body.email,
        password=body.password,
        display_name=body.display_name,
        user_agent=request.headers.get("user-agent"),
        ip_address=client_ip(request),
    )
    _cookie(response, result.token)
    sent = False
    if result.dev_token:
        sent = await deliver_auth_email(recipient=result.user.email, kind="email_verify", token=result.dev_token)
    show_token = result.dev_token if settings.expose_dev_tokens and not sent else None
    return {"user": user_to_dict(result.user), "dev_verification_token": show_token, "email_sent": sent}


@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response, session: AsyncSession = Depends(get_session)):
    enforce_rate(f"login:{client_ip(request)}", limit=10, window_seconds=600)
    result = await login_user(
        session,
        email=body.email,
        password=body.password,
        user_agent=request.headers.get("user-agent"),
        ip_address=client_ip(request),
    )
    _cookie(response, result.token)
    return {"user": user_to_dict(result.user)}


@router.post("/logout")
async def logout(response: Response, user: CurrentUser = Depends(require_user), session: AsyncSession = Depends(get_session)):
    await logout_user(session, user.session_id)
    response.delete_cookie(settings.cookie_name, path="/")
    return {"message": "Signed out."}


@router.get("/me")
async def me(user: CurrentUser = Depends(require_user), session: AsyncSession = Depends(get_session)):
    row = await session.get(User, user.id)
    return {"user": user_to_dict(row)}


@router.patch("/profile")
async def profile(body: ProfileUpdate, user: CurrentUser = Depends(require_user), session: AsyncSession = Depends(get_session)):
    updated = await update_profile(session, user.id, body.model_dump(exclude_unset=True))
    return {"user": user_to_dict(updated)}


@router.post("/password/forgot")
async def forgot(body: ForgotPasswordRequest, request: Request, session: AsyncSession = Depends(get_session)):
    enforce_rate(f"forgot:{client_ip(request)}", limit=5, window_seconds=600)
    token = await request_password_reset(session, body.email)
    sent = False
    if token:
        sent = await deliver_auth_email(recipient=body.email.strip().lower(), kind="password_reset", token=token)
    payload = {
        "message": "If an account exists for that email, a reset link is on its way."
        if sent
        else "If an account exists for that email, a reset link has been created.",
        "email_sent": sent,
    }
    if token and settings.expose_dev_tokens and not sent:
        payload["dev_token"] = token
    return payload


@router.post("/password/reset")
async def reset(body: ResetPasswordRequest, session: AsyncSession = Depends(get_session)):
    await reset_password(session, body.token, body.password)
    return {"message": "Password updated. Sign in with the new password."}


@router.post("/password/change")
async def change(body: ChangePasswordRequest, user: CurrentUser = Depends(require_user), session: AsyncSession = Depends(get_session)):
    await change_password(
        session,
        user_id=user.id,
        session_id=user.session_id,
        current_password=body.current_password,
        new_password=body.new_password,
    )
    return {"message": "Password changed. Other sessions were signed out."}


@router.post("/verify-email/request")
async def verification_request(user: CurrentUser = Depends(require_user), session: AsyncSession = Depends(get_session)):
    token = await request_verification(session, user.id)
    sent = False
    if token:
        sent = await deliver_auth_email(recipient=user.email, kind="email_verify", token=token)
    payload = {
        "message": "Verification email sent." if sent else "Verification link created.",
        "email_sent": sent,
    }
    if token and settings.expose_dev_tokens and not sent:
        payload["dev_token"] = token
    return payload


@router.post("/verify-email")
async def verification(body: VerifyEmailRequest, session: AsyncSession = Depends(get_session)):
    await verify_email(session, body.token)
    return {"message": "Email verified."}


@router.delete("/account")
async def remove_account(
    body: DeleteAccountRequest,
    response: Response,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    row = await session.get(User, user.id)
    if row is None or not verify_password(body.password, row.password_hash):
        from app.core.errors import AppError

        raise AppError("invalid_credentials", "The password is incorrect.", 401)
    await delete_account(session, row)
    response.delete_cookie(settings.cookie_name, path="/")
    return {"message": "Account deleted."}
