import asyncio
import logging
import os
import socket
import uuid

from app.core.config import settings
from app.core.errors import ProcessingError
from app.db.session import SessionLocal
from app.models import Job
from app.services.jobs import RETRYABLE_CODES, claim_job, fail_job, finish_job

logger = logging.getLogger(__name__)


async def process_next_job(worker_id: str) -> bool:
    job_id = await claim_job(worker_id)
    if job_id is None:
        return False
    async with SessionLocal() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return True
        job_type = job.job_type
        payload = dict(job.payload or {})
        document_id = job.document_id
    try:
        if job_type == "process_document" and document_id is not None:
            outcome = await _process_document(document_id)
            await _finish_document_job(job_id, outcome)
        elif job_type == "evaluation_run":
            from app.services.evaluation import run_evaluation

            await run_evaluation(uuid.UUID(payload["run_id"]))
            await finish_job(job_id, "succeeded", None)
        else:
            await finish_job(job_id, "dead", "unsupported_job")
    except ProcessingError as exc:
        category = exc.code if exc.code in RETRYABLE_CODES else "processing_failed"
        await fail_job(job_id, category)
    except Exception as exc:
        logger.exception("job failed", extra={"component": "worker", "error_category": type(exc).__name__})
        await fail_job(job_id, "unexpected")
    return True


async def _process_document(document_id: uuid.UUID) -> str:
    from app.services.processing import process_document

    return await process_document(document_id)


async def _finish_document_job(job_id: uuid.UUID, outcome: str) -> None:
    if outcome == "completed" or outcome == "missing":
        await finish_job(job_id, "succeeded" if outcome == "completed" else "cancelled", None)
        return
    if outcome == "cancelled":
        await finish_job(job_id, "cancelled", None)
        return
    if outcome.startswith("failed:"):
        code = outcome.split(":", 1)[1]
        if code in RETRYABLE_CODES:
            await fail_job(job_id, code)
        else:
            await finish_job(job_id, "dead", code)
        return
    await finish_job(job_id, "succeeded", None)


async def worker_loop(stop_event: asyncio.Event, worker_id: str | None = None) -> None:
    worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}"
    while not stop_event.is_set():
        worked = False
        try:
            worked = await process_next_job(worker_id)
        except Exception:
            logger.exception("worker loop failed", extra={"component": "worker", "error_category": "loop"})
        if worked:
            continue
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.worker_poll_seconds)
        except TimeoutError:
            continue


def main() -> None:
    from app.core.logging import configure_logging
    from app.services.jobs import recover_stuck_work

    configure_logging()

    async def run() -> None:
        await recover_stuck_work()
        stop_event = asyncio.Event()
        try:
            await worker_loop(stop_event)
        except asyncio.CancelledError:
            stop_event.set()
            raise

    asyncio.run(run())


if __name__ == "__main__":
    main()
