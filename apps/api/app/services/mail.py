import asyncio
import logging
import smtplib
from email.message import EmailMessage
from urllib.parse import quote

from app.core.config import settings

logger = logging.getLogger(__name__)


def auth_link(kind: str, token: str) -> str:
    base = settings.web_base_url.rstrip("/")
    path = "verify-email" if kind == "email_verify" else "reset-password"
    return f"{base}/{path}?token={quote(token, safe='')}"


def _message(kind: str, recipient: str, token: str) -> EmailMessage:
    link = auth_link(kind, token)
    if kind == "email_verify":
        subject = "Verify your ContextAI email"
        body = (
            "Confirm this address for your ContextAI account.\n\n"
            f"{link}\n\n"
            f"This link expires in {settings.email_verify_ttl_hours} hours. "
            "If you did not create the account, ignore this message."
        )
    else:
        subject = "Reset your ContextAI password"
        body = (
            "Use this link to choose a new ContextAI password.\n\n"
            f"{link}\n\n"
            f"This link expires in {settings.password_reset_ttl_minutes} minutes and works once. "
            "If you did not request a reset, ignore this message."
        )
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from
    message["To"] = recipient
    message.set_content(body)
    return message


def _send_sync(message: EmailMessage) -> None:
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as client:
        client.ehlo()
        client.starttls()
        client.ehlo()
        client.login(settings.smtp_username or "", settings.smtp_password or "")
        client.send_message(message)


async def deliver_auth_email(*, recipient: str, kind: str, token: str) -> bool:
    if not settings.mail_configured:
        return False
    message = _message(kind, recipient, token)
    try:
        await asyncio.to_thread(_send_sync, message)
    except Exception as exc:
        logger.warning(
            "auth email failed",
            extra={"component": "mail", "error_category": type(exc).__name__},
        )
        return False
    logger.info("auth email sent", extra={"component": "mail", "error_category": kind})
    return True
