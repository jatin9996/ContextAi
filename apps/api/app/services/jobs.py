import logging
import uuid
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.time import utcnow
from app.db.session import SessionLocal
from app.models import Document, Job, Message

logger = logging.getLogger(__name__)

RETRYABLE_CODES = {"processing_failed", "embedding_dimensions", "dependency_missing"}


async def enqueue_job(
    session: AsyncSession,
    *,
    job_type: str,
    payload: dict,
    document_id: uuid.UUID | None = None,
    max_attempts: int = 3,
) -> Job:
    job = Job(
        job_type=job_type,
        payload=payload,
        status="queued",
        document_id=document_id,
        max_attempts=max_attempts,
        run_after=utcnow(),
    )
    session.add(job)
    await session.flush()
    return job


async def claim_job(worker_id: str) -> uuid.UUID | None:
    async with SessionLocal() as session:
        async with session.begin():
            statement = (
                select(Job)
                .where(Job.status == "queued", Job.run_after <= utcnow(), Job.attempts < Job.max_attempts)
                .order_by(Job.created_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            job = (await session.execute(statement)).scalar_one_or_none()
            if job is None:
                return None
            job.status = "running"
            job.attempts += 1
            job.locked_at = utcnow()
            job.locked_by = worker_id[:80]
            job.updated_at = utcnow()
            return job.id


async def finish_job(job_id: uuid.UUID, status: str, error: str | None) -> None:
    async with SessionLocal() as session:
        async with session.begin():
            job = await session.get(Job, job_id)
            if job is None:
                return
            job.status = status
            job.last_error = error[:400] if error else None
            job.updated_at = utcnow()


async def fail_job(job_id: uuid.UUID, category: str) -> None:
    async with SessionLocal() as session:
        async with session.begin():
            job = await session.get(Job, job_id)
            if job is None:
                return
            job.last_error = category[:400]
            job.updated_at = utcnow()
            retryable = RETRYABLE_CODES | {"unexpected"}
            retry = job.attempts < job.max_attempts and category in retryable
            if retry:
                job.status = "queued"
                job.run_after = utcnow() + timedelta(seconds=min(60, 2**job.attempts))
            else:
                job.status = "dead"
            if job.document_id:
                document = await session.get(Document, job.document_id)
                if document and document.status == "processing":
                    document.updated_at = utcnow()
                    if job.status == "queued":
                        document.status = "queued"
                    elif document.status != "cancelled":
                        document.status = "failed"
                        document.error_code = category[:64]
                        document.error_message = "Document processing failed."


async def recover_stuck_work() -> None:
    job_cutoff = utcnow() - timedelta(minutes=settings.stuck_job_minutes)
    message_cutoff = utcnow() - timedelta(minutes=settings.stuck_stream_minutes)
    async with SessionLocal() as session:
        async with session.begin():
            stuck_jobs = list(
                await session.scalars(select(Job).where(Job.status == "running", Job.locked_at < job_cutoff))
            )
            for job in stuck_jobs:
                job.updated_at = utcnow()
                if job.attempts < job.max_attempts:
                    job.status = "queued"
                    job.run_after = utcnow()
                    job.last_error = "recovered"
                else:
                    job.status = "dead"
                    job.last_error = "stuck_timeout"
                if job.document_id:
                    document = await session.get(Document, job.document_id)
                    if document and document.status == "processing":
                        document.updated_at = utcnow()
                        if job.status == "queued":
                            document.status = "queued"
                        else:
                            document.status = "failed"
                            document.error_code = "processing_failed"
                            document.error_message = "Processing was interrupted and could not be recovered."
            await session.execute(
                update(Message)
                .where(Message.status == "streaming", Message.created_at < message_cutoff)
                .values(status="incomplete", error_code="interrupted")
            )
    if stuck_jobs:
        logger.info("recovered stuck jobs", extra={"component": "jobs", "count": len(stuck_jobs)})
