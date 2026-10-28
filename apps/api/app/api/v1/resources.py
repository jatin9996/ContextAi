import uuid
from datetime import date

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_user
from app.core.errors import AppError
from app.db.session import get_session
from app.models import Conversation, DocumentChunk, EvaluationCase, EvaluationResult, EvaluationRun, Memory, Message, Task, ToolOperation
from app.schemas.contracts import (
    EvaluationRunCreate,
    MemoryCreate,
    MemoryResolve,
    MemoryUpdate,
    SearchRequest,
    TaskCreate,
    TaskExtractRequest,
    TaskUpdate,
)
from app.serializers import memory_to_dict, operation_to_dict, run_to_dict, task_to_dict
from app.services.audit import record_audit
from app.services.dashboard import dashboard_for
from app.services.evaluation import enqueue_evaluation
from app.services.memories import create_memory, delete_memory, resolve_memory, update_memory
from app.services.models_user import load_user
from app.services.retrieval import retrieve_chunks
from app.services.tasks import create_task, extract_task_drafts, get_owned_task, save_extracted_tasks, update_task
from app.services.textutil import excerpt_around
from app.services.tools import confirm_operation, reject_operation

router = APIRouter(tags=["workspace"])


@router.get("/dashboard")
async def dashboard(user: CurrentUser = Depends(require_user), session: AsyncSession = Depends(get_session)):
    row = await load_user(session, user.id)
    return await dashboard_for(session, row)


@router.post("/search")
async def search(body: SearchRequest, user: CurrentUser = Depends(require_user), session: AsyncSession = Depends(get_session)):
    if body.file_type is not None and body.file_type not in {"pdf", "txt", "md", "docx"}:
        raise AppError("invalid_arguments", "Unsupported file type filter.")
    outcome = await retrieve_chunks(
        session,
        user_id=user.id,
        query=body.query,
        document_id=body.document_id,
        extension=body.file_type,
        uploaded_after=body.uploaded_after,
        limit=body.limit,
    )
    groups: dict[str, dict] = {}
    for chunk in outcome.chunks:
        key = str(chunk.document_id)
        group = groups.setdefault(
            key,
            {
                "document_id": key,
                "label": chunk.label,
                "filename": chunk.filename,
                "extension": chunk.extension,
                "hits": [],
            },
        )
        group["hits"].append(
            {
                "chunk_id": str(chunk.chunk_id),
                "excerpt": excerpt_around(chunk.content, body.query),
                "page_start": chunk.page_start,
                "section": chunk.section,
                "score": round(chunk.score, 4),
            }
        )
    return {
        "query": body.query,
        "groups": list(groups.values()),
        "diagnostics": {
            "retrieved_count": outcome.retrieved_count,
            "selected_count": len(outcome.chunks),
            "retrieval_ms": round(outcome.latency_ms, 2),
        },
    }


@router.get("/memories")
async def list_memories(
    status: str = "active",
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    filters = [Memory.user_id == user.id]
    if status != "all":
        filters.append(Memory.status == status)
    total = await session.scalar(select(func.count()).select_from(Memory).where(*filters))
    rows = await session.scalars(
        select(Memory).where(*filters).order_by(Memory.updated_at.desc()).limit(limit).offset(offset)
    )
    return {"items": [memory_to_dict(row) for row in rows], "total": int(total or 0)}


@router.post("/memories", status_code=201)
async def post_memory(
    body: MemoryCreate,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    if not user.memory_enabled:
        raise AppError("memory_disabled", "Turn memory on in settings before saving memories.", 409)
    memory, outcome = await create_memory(
        session,
        user_id=user.id,
        content=body.content,
        source="user",
        invoked_by="user",
        confirm_conflicts=body.confirm_conflicts,
    )
    await record_audit(
        session,
        user_id=user.id,
        action="memory_saved",
        resource_type="memory",
        resource_id=memory.id,
        metadata={"status": memory.status},
    )
    return {"memory": memory_to_dict(memory), "outcome": outcome}


@router.patch("/memories/{memory_id}")
async def patch_memory(
    memory_id: uuid.UUID,
    body: MemoryUpdate,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    memory = await update_memory(
        session,
        user_id=user.id,
        memory_id=memory_id,
        content=body.content,
        status=body.status,
    )
    return memory_to_dict(memory)


@router.post("/memories/{memory_id}/resolve")
async def post_resolve(
    memory_id: uuid.UUID,
    body: MemoryResolve,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    memory = await resolve_memory(session, user_id=user.id, memory_id=memory_id, action=body.action)
    return memory_to_dict(memory)


@router.delete("/memories/{memory_id}")
async def remove_memory(
    memory_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    await delete_memory(session, user_id=user.id, memory_id=memory_id)
    return {"message": "Memory deleted."}


@router.get("/tasks")
async def list_tasks(
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    filters = [Task.user_id == user.id]
    if status:
        filters.append(Task.status == status)
    total = await session.scalar(select(func.count()).select_from(Task).where(*filters))
    rows = await session.scalars(select(Task).where(*filters).order_by(Task.updated_at.desc()).limit(limit).offset(offset))
    return {"items": [task_to_dict(row) for row in rows], "total": int(total or 0)}


@router.post("/tasks", status_code=201)
async def post_task(
    body: TaskCreate,
    user: CurrentUser = Depends(require_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_session),
):
    due = _parse_due(body.due_date)
    task, duplicate = await create_task(
        session,
        user_id=user.id,
        title=body.title,
        description=body.description,
        due_date=due,
        due_label=body.due_label,
        priority=body.priority,
        status=body.status,
        source_type="manual",
        idempotency_key=idempotency_key,
        invoked_by="user",
        allow_duplicate=body.allow_duplicate,
    )
    if not duplicate:
        await record_audit(
            session,
            user_id=user.id,
            action="task_created",
            resource_type="task",
            resource_id=task.id,
            metadata={"title": task.title, "status": task.status},
        )
    return task_to_dict(task, duplicate=duplicate)


@router.post("/tasks/extract")
async def extract_tasks(
    body: TaskExtractRequest,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    if body.document_id is None and body.conversation_id is None:
        raise AppError("invalid_arguments", "Choose a document or a conversation.")
    if body.document_id is not None:
        from app.models import Document

        document = await session.get(Document, body.document_id)
        if document is None or document.user_id != user.id:
            raise AppError("not_found", "Document not found.", 404)
        chunks = list(
            await session.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == document.id, DocumentChunk.user_id == user.id)
                .order_by(DocumentChunk.chunk_index)
            )
        )
        source_text = "\n".join(chunk.content for chunk in chunks)
        source_type = "document"
        source_id = document.id
    else:
        conversation = await session.get(Conversation, body.conversation_id)
        if conversation is None or conversation.user_id != user.id:
            raise AppError("not_found", "Conversation not found.", 404)
        messages = list(
            await session.scalars(
                select(Message).where(Message.conversation_id == conversation.id, Message.user_id == user.id)
            )
        )
        source_text = "\n".join(message.content for message in messages)
        source_type = "conversation"
        source_id = conversation.id
    drafts = extract_task_drafts(source_text)
    saved = await save_extracted_tasks(
        session,
        user_id=user.id,
        drafts=drafts,
        source_type=source_type,
        source_id=source_id,
        source_text=source_text,
    )
    return {"items": [task_to_dict(task, duplicate=duplicate) for task, duplicate in saved]}


@router.patch("/tasks/{task_id}")
async def patch_task(
    task_id: uuid.UUID,
    body: TaskUpdate,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    if body.status and body.status not in {"proposed", "open", "completed", "cancelled"}:
        raise AppError("invalid_arguments", "That task status is not valid.")
    if body.priority and body.priority not in {"low", "medium", "high"}:
        raise AppError("invalid_arguments", "Priority must be low, medium, or high.")
    changes = body.model_dump(exclude_unset=True)
    if "due_date" in changes:
        changes["due_date"] = _parse_due(changes["due_date"]) if changes["due_date"] else None
    task = await update_task(session, user_id=user.id, task_id=task_id, title=None, changes=changes)
    return task_to_dict(task)


@router.delete("/tasks/{task_id}")
async def remove_task(
    task_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    task = await get_owned_task(session, user.id, task_id)
    await session.delete(task)
    return {"message": "Task deleted."}


@router.get("/tools/operations")
async def list_operations(
    limit: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    rows = await session.scalars(
        select(ToolOperation).where(ToolOperation.user_id == user.id).order_by(ToolOperation.created_at.desc()).limit(limit)
    )
    return {"items": [operation_to_dict(row) for row in rows]}


@router.post("/tools/operations/{operation_id}/confirm")
async def confirm(
    operation_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    result = await confirm_operation(session, user.id, operation_id)
    return {
        "status": result.status,
        "message": result.message,
        "operation_id": result.operation_id,
        "resource_id": result.resource_id,
        "error_category": result.error_category,
    }


@router.post("/tools/operations/{operation_id}/reject")
async def reject(
    operation_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    operation = await reject_operation(session, user.id, operation_id)
    return operation_to_dict(operation)


@router.get("/evaluations/datasets")
async def datasets(user: CurrentUser = Depends(require_user), session: AsyncSession = Depends(get_session)):
    del user
    from app.models import EvaluationDataset

    rows = list(await session.scalars(select(EvaluationDataset).order_by(EvaluationDataset.created_at)))
    payload = []
    for row in rows:
        count = await session.scalar(
            select(func.count()).select_from(EvaluationCase).where(EvaluationCase.dataset_id == row.id)
        )
        payload.append(
            {
                "id": str(row.id),
                "name": row.name,
                "description": row.description,
                "case_count": int(count or 0),
            }
        )
    return {"items": payload}


@router.post("/evaluations/runs", status_code=202)
async def start_run(
    body: EvaluationRunCreate,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    run = await enqueue_evaluation(session, user_id=user.id, use_sample_corpus=body.use_sample_corpus)
    return run_to_dict(run)


@router.get("/evaluations/runs")
async def list_runs(
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    rows = await session.scalars(
        select(EvaluationRun).where(EvaluationRun.user_id == user.id).order_by(EvaluationRun.created_at.desc()).limit(20)
    )
    return {"items": [run_to_dict(row) for row in rows]}


@router.get("/evaluations/runs/{run_id}")
async def get_run(
    run_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    run = await session.get(EvaluationRun, run_id)
    if run is None or run.user_id != user.id:
        raise AppError("not_found", "Evaluation run not found.", 404)
    results = list(
        await session.scalars(select(EvaluationResult).where(EvaluationResult.run_id == run.id))
    )
    cases = {
        case.id: case
        for case in await session.scalars(select(EvaluationCase).where(EvaluationCase.dataset_id == run.dataset_id))
    }
    return {
        "run": run_to_dict(run),
        "results": [
            {
                "case_id": str(result.case_id),
                "question": cases[result.case_id].question if result.case_id in cases else None,
                "case_type": cases[result.case_id].case_type if result.case_id in cases else None,
                "passed": result.passed,
                "failure_reason": result.failure_reason,
                "metrics": result.metrics,
            }
            for result in results
        ],
    }


def _parse_due(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise AppError("invalid_arguments", "Due dates must use YYYY-MM-DD.") from exc
