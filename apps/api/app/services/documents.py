import hashlib
import logging
import uuid
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.core.time import utcnow
from app.models import Document, DocumentChunk, Job
from app.services.audit import record_audit
from app.services.files import ValidatedUpload
from app.services.jobs import enqueue_job
from app.services.storage import get_storage

logger = logging.getLogger(__name__)


async def get_owned_document(session: AsyncSession, user_id: uuid.UUID, document_id: uuid.UUID) -> Document:
    document = await session.get(Document, document_id)
    if document is None or document.user_id != user_id:
        raise AppError("not_found", "Document not found.", 404)
    return document


async def create_document(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    upload: ValidatedUpload,
    enqueue: bool = True,
) -> Document:
    document_id = uuid.uuid4()
    key = f"{user_id}/{document_id}/original"
    storage = get_storage()
    await storage.save(key, upload.data, upload.mime_type)
    label = Path(upload.filename).stem[:200] or upload.filename
    document = Document(
        id=document_id,
        user_id=user_id,
        filename=upload.filename,
        label=label,
        mime_type=upload.mime_type,
        extension=upload.extension,
        size_bytes=upload.size_bytes,
        storage_key=key,
        content_sha256=hashlib.sha256(upload.data).hexdigest(),
        status="queued",
        chunk_count=0,
    )
    session.add(document)
    try:
        await session.flush()
        if enqueue:
            await enqueue_job(
                session,
                job_type="process_document",
                payload={"document_id": str(document_id)},
                document_id=document_id,
            )
        await record_audit(
            session,
            user_id=user_id,
            action="document_uploaded",
            resource_type="document",
            resource_id=document_id,
            metadata={"filename": upload.filename, "label": label, "status": "queued"},
        )
    except Exception:
        await storage.delete(key)
        raise
    return document


async def list_documents(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    limit: int,
    offset: int,
) -> tuple[list[Document], int]:
    total = await session.scalar(select(func.count()).select_from(Document).where(Document.user_id == user_id))
    rows = await session.scalars(
        select(Document)
        .where(Document.user_id == user_id)
        .order_by(Document.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(rows), int(total or 0)


async def rename_document(session: AsyncSession, user_id: uuid.UUID, document_id: uuid.UUID, label: str) -> Document:
    document = await get_owned_document(session, user_id, document_id)
    document.label = label.strip()[:200]
    document.updated_at = utcnow()
    return document


async def request_cancel(session: AsyncSession, user_id: uuid.UUID, document_id: uuid.UUID) -> Document:
    document = await session.get(Document, document_id, with_for_update=True)
    if document is None or document.user_id != user_id:
        raise AppError("not_found", "Document not found.", 404)
    if document.status in {"completed", "failed", "cancelled"}:
        raise AppError("invalid_state", "This document is not processing.", 409)
    document.cancel_requested = True
    document.updated_at = utcnow()
    if document.status in {"uploaded", "queued"}:
        document.status = "cancelled"
        await session.execute(
            update(Job)
            .where(Job.document_id == document.id, Job.status == "queued")
            .values(status="cancelled", updated_at=utcnow())
        )
    return document


async def retry_document(session: AsyncSession, user_id: uuid.UUID, document_id: uuid.UUID) -> Document:
    document = await session.get(Document, document_id, with_for_update=True)
    if document is None or document.user_id != user_id:
        raise AppError("not_found", "Document not found.", 404)
    if document.status not in {"failed", "cancelled"}:
        raise AppError("invalid_state", "Only failed or cancelled documents can be retried.", 409)
    active = await session.scalar(
        select(Job.id).where(Job.document_id == document.id, Job.status.in_(("queued", "running")))
    )
    document.status = "queued"
    document.cancel_requested = False
    document.error_code = None
    document.error_message = None
    document.updated_at = utcnow()
    if active is None:
        try:
            await enqueue_job(
                session,
                job_type="process_document",
                payload={"document_id": str(document.id)},
                document_id=document.id,
            )
        except IntegrityError as exc:
            raise AppError("invalid_state", "This document is already queued.", 409) from exc
    return document


async def remove_document(session: AsyncSession, user_id: uuid.UUID, document_id: uuid.UUID) -> None:
    document = await session.get(Document, document_id, with_for_update=True)
    if document is None or document.user_id != user_id:
        raise AppError("not_found", "Document not found.", 404)
    storage_key = document.storage_key
    filename = document.filename
    await record_audit(
        session,
        user_id=user_id,
        action="document_deleted",
        resource_type="document",
        resource_id=document.id,
        metadata={"filename": filename, "status": "deleted"},
    )
    await session.delete(document)
    await session.commit()
    try:
        await get_storage().delete(storage_key)
    except Exception:
        logger.warning("stored file cleanup failed", extra={"component": "documents", "error_category": "storage"})


async def list_chunks(session: AsyncSession, user_id: uuid.UUID, document_id: uuid.UUID) -> list[DocumentChunk]:
    await get_owned_document(session, user_id, document_id)
    rows = await session.scalars(
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document_id, DocumentChunk.user_id == user_id)
        .order_by(DocumentChunk.chunk_index)
    )
    return list(rows)
