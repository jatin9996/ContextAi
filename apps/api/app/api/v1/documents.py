import uuid

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, enforce_rate, require_user
from app.core.config import settings
from app.core.errors import AppError
from app.db.session import get_session
from app.schemas.contracts import DocumentUpdate
from app.serializers import document_to_dict
from app.services.documents import (
    create_document,
    get_owned_document,
    list_chunks,
    list_documents,
    remove_document,
    rename_document,
    request_cancel,
    retry_document,
)
from app.services.files import validate_upload
from app.services.storage import get_storage

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("", status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    enforce_rate(f"upload:{user.id}", limit=20, window_seconds=3600)
    buffer = bytearray()
    while True:
        piece = await file.read(1024 * 1024)
        if not piece:
            break
        if len(buffer) + len(piece) > settings.max_upload_bytes:
            raise AppError("file_too_large", "The file is larger than 20 MB.")
        buffer.extend(piece)
    upload = validate_upload(file.filename or "upload", bytes(buffer), max_bytes=settings.max_upload_bytes)
    document = await create_document(session, user_id=user.id, upload=upload)
    return document_to_dict(document)


@router.post("/sample", status_code=201)
async def upload_sample_brief(
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    enforce_rate(f"upload:{user.id}", limit=20, window_seconds=3600)
    path = settings.sample_document_path.with_name("project-brief.pdf")
    if not path.is_file():
        raise AppError("not_found", "The sample brief is not installed with this API.", 404)
    upload = validate_upload(path.name, path.read_bytes(), max_bytes=settings.max_upload_bytes)
    document = await create_document(session, user_id=user.id, upload=upload)
    return document_to_dict(document)


@router.get("")
async def get_documents(
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    rows, total = await list_documents(session, user.id, limit=limit, offset=offset)
    return {"items": [document_to_dict(row) for row in rows], "total": total}


@router.get("/{document_id}")
async def get_document(
    document_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    document = await get_owned_document(session, user.id, document_id)
    return document_to_dict(document)


@router.get("/{document_id}/status")
async def document_status(
    document_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    document = await get_owned_document(session, user.id, document_id)
    return {
        "id": str(document.id),
        "status": document.status,
        "error_code": document.error_code,
        "error_message": document.error_message,
        "chunk_count": document.chunk_count,
        "cancel_requested": document.cancel_requested,
    }


@router.get("/{document_id}/chunks")
async def document_chunks(
    document_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    chunks = await list_chunks(session, user.id, document_id)
    return {
        "items": [
            {
                "id": str(chunk.id),
                "chunk_index": chunk.chunk_index,
                "content": chunk.content,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "section": chunk.section,
            }
            for chunk in chunks
        ]
    }


@router.get("/{document_id}/file")
async def download_document(
    document_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    document = await get_owned_document(session, user.id, document_id)
    data = await get_storage().load(document.storage_key)
    safe_name = "".join(char if char.isalnum() or char in "._-" else "_" for char in document.filename)[:120]
    return Response(
        content=data,
        media_type=document.mime_type,
        headers={"Content-Disposition": f'attachment; filename="{safe_name or "document"}"'},
    )


@router.patch("/{document_id}")
async def update_document(
    document_id: uuid.UUID,
    body: DocumentUpdate,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    document = await rename_document(session, user.id, document_id, body.label)
    return document_to_dict(document)


@router.post("/{document_id}/cancel")
async def cancel_document(
    document_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    document = await request_cancel(session, user.id, document_id)
    return document_to_dict(document)


@router.post("/{document_id}/retry")
async def retry(
    document_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    document = await retry_document(session, user.id, document_id)
    return document_to_dict(document)


@router.delete("/{document_id}")
async def delete_document(
    document_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    await remove_document(session, user.id, document_id)
    return {"message": "Document deleted."}
