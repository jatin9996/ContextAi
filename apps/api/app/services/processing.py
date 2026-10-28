import logging
import uuid

from sqlalchemy import delete, select

from app.core.constants import EMBEDDING_DIM
from app.core.errors import ProcessingError
from app.core.time import utcnow
from app.db.session import SessionLocal
from app.models import Document, DocumentChunk, DocumentEmbedding
from app.services.audit import record_audit
from app.services.chunking import chunk_pages
from app.services.embeddings import get_embeddings
from app.services.extract import extract_document
from app.services.jobs import RETRYABLE_CODES
from app.services.storage import get_storage
from app.core.config import settings

logger = logging.getLogger(__name__)


async def process_document(document_id: uuid.UUID) -> str:
    storage = get_storage()
    async with SessionLocal() as session:
        async with session.begin():
            document = await session.get(Document, document_id, with_for_update=True)
            if document is None:
                return "missing"
            if document.cancel_requested or document.status == "cancelled":
                document.status = "cancelled"
                document.cancel_requested = False
                document.updated_at = utcnow()
                return "cancelled"
            if document.status not in {"queued", "processing"}:
                return "failed:invalid_state"
            document.status = "processing"
            document.error_code = None
            document.error_message = None
            document.updated_at = utcnow()
            storage_key = document.storage_key
            extension = document.extension
            user_id = document.user_id
            filename = document.filename

    try:
        data = await storage.load(storage_key)
        pages = extract_document(extension, data)
        drafts = chunk_pages(pages, chunk_size=settings.chunk_size, overlap=settings.chunk_overlap)
        if not drafts:
            raise ProcessingError("no_extractable_text", "No text could be extracted from this file.")
        if len(drafts) > settings.max_chunks:
            raise ProcessingError(
                "too_many_chunks",
                "This document is too large to index in one pass. Split it into smaller files.",
            )
        vectors = await get_embeddings().embed([draft.content for draft in drafts])
        if any(len(vector) != EMBEDDING_DIM for vector in vectors):
            raise ProcessingError("embedding_dimensions", "The embedding provider returned an unexpected vector size.")
    except ProcessingError as exc:
        if exc.code in RETRYABLE_CODES:
            raise
        await _mark_failed(document_id, exc.code, exc.message)
        return f"failed:{exc.code}"
    except Exception:
        logger.exception("document processing failed", extra={"component": "processing", "error_category": "processing_failed"})
        raise

    async with SessionLocal() as session:
        async with session.begin():
            document = await session.get(Document, document_id, with_for_update=True)
            if document is None:
                return "missing"
            if document.cancel_requested or document.status == "cancelled":
                document.status = "cancelled"
                document.cancel_requested = False
                document.updated_at = utcnow()
                return "cancelled"
            await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
            await session.flush()
            for index, (draft, vector) in enumerate(zip(drafts, vectors, strict=True)):
                chunk_id = uuid.uuid4()
                session.add(
                    DocumentChunk(
                        id=chunk_id,
                        document_id=document_id,
                        user_id=user_id,
                        chunk_index=index,
                        content=draft.content,
                        page_start=draft.page_start,
                        page_end=draft.page_end,
                        section=draft.section,
                        token_count=draft.token_count,
                    )
                )
                session.add(
                    DocumentEmbedding(
                        chunk_id=chunk_id,
                        document_id=document_id,
                        user_id=user_id,
                        embedding=vector,
                    )
                )
            page_numbers = [page.page for page in pages if page.page]
            document.status = "completed"
            document.chunk_count = len(drafts)
            document.page_count = max(page_numbers) if page_numbers else None
            document.error_code = None
            document.error_message = None
            document.cancel_requested = False
            document.updated_at = utcnow()
            await record_audit(
                session,
                user_id=user_id,
                action="document_processed",
                resource_type="document",
                resource_id=document_id,
                metadata={"filename": filename, "count": len(drafts), "status": "completed"},
            )
    return "completed"


async def _mark_failed(document_id: uuid.UUID, code: str, message: str) -> None:
    async with SessionLocal() as session:
        async with session.begin():
            document = await session.get(Document, document_id, with_for_update=True)
            if document is None:
                return
            if document.cancel_requested or document.status == "cancelled":
                document.status = "cancelled"
                document.cancel_requested = False
                document.updated_at = utcnow()
                return
            document.status = "failed"
            document.error_code = code[:64]
            document.error_message = message[:500]
            document.updated_at = utcnow()
            await record_audit(
                session,
                user_id=document.user_id,
                action="document_failed",
                resource_type="document",
                resource_id=document.id,
                metadata={"filename": document.filename, "error_code": code, "status": "failed"},
            )


async def chunk_count(document_id: uuid.UUID) -> int:
    async with SessionLocal() as session:
        rows = await session.scalars(select(DocumentChunk.id).where(DocumentChunk.document_id == document_id))
        return len(list(rows))
