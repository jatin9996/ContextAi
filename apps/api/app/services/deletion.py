import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import email_fingerprint
from app.models import Document, EvaluationRun, Job, User
from app.services.audit import record_audit
from app.services.storage import get_storage

logger = logging.getLogger(__name__)


async def delete_account(session: AsyncSession, user: User) -> None:
    """Immediately delete the account and dependent rows.

    Storage objects are removed after the database commit. A failed object delete
    is logged for a later cleanup pass; the account itself is already gone.
    Audit retains only a hash of the email, and the user id is cleared by the
    foreign key when the user row is deleted.
    """
    keys = list(await session.scalars(select(Document.storage_key).where(Document.user_id == user.id)))
    run_ids = [str(item) for item in await session.scalars(select(EvaluationRun.id).where(EvaluationRun.user_id == user.id))]
    if run_ids:
        jobs = list(await session.scalars(select(Job).where(Job.job_type == "evaluation_run")))
        for job in jobs:
            if str((job.payload or {}).get("run_id")) in run_ids:
                await session.delete(job)
    await record_audit(
        session,
        user_id=user.id,
        action="account_deleted",
        resource_type="user",
        resource_id=user.id,
        metadata={"email_sha256": email_fingerprint(user.email)},
    )
    await session.delete(user)
    await session.commit()
    storage = get_storage()
    for key in keys:
        try:
            await storage.delete(key)
        except Exception:
            logger.warning("account file cleanup failed", extra={"component": "deletion", "error_category": "storage"})
