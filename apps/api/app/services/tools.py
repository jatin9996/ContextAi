import re
import uuid
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.core.time import utcnow
from app.models import Document, Task, ToolOperation
from app.services.llm import generate_text
from app.services.memories import create_memory
from app.services.policies import authorize_tool_call
from app.services.retrieval import retrieve_chunks, retrieve_memories
from app.services.tasks import create_task, update_task
from app.services.textutil import trim_text

PREFERENCE_RE = re.compile(r"\bI (?:prefer|like to use|always use|want)\b[^.!\n]{3,160}", re.IGNORECASE)


class SearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=500)


class CreateTaskArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=3, max_length=200)
    description: str = ""
    due_date: str | None = None
    due_label: str | None = None
    priority: str | None = None
    status: str = "proposed"


class UpdateTaskArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: uuid.UUID | None = None
    title: str | None = None
    status: str | None = None


class ListTasksArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str | None = "open"


class MemoryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=3, max_length=4000)


class RetrieveMemoryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=500)


class SummarizeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: uuid.UUID | None = None
    label: str | None = None

    @model_validator(mode="after")
    def require_target(self) -> "SummarizeArgs":
        if self.document_id is None and not (self.label and self.label.strip()):
            raise ValueError("document_id or label is required")
        return self


@dataclass
class ToolContext:
    session: AsyncSession
    user_id: uuid.UUID
    invoked_by: str = "user"
    approved: bool = False
    idempotency_key: str | None = None
    operation_id: uuid.UUID | None = None


@dataclass
class ToolResult:
    status: str
    message: str
    error_category: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    citations: list = field(default_factory=list)
    data: dict = field(default_factory=dict)
    operation_id: str | None = None


@dataclass
class ToolSpec:
    name: str
    description: str
    model: type[BaseModel]
    consequential: bool
    handler: object


def parse_user_command(text: str) -> dict | None:
    stripped = text.strip()
    lowered = stripped.lower()
    if lowered in {"/tasks", "list tasks", "list my tasks"}:
        return {"name": "list_tasks", "arguments": {"status": "open"}, "approved": True}
    if lowered.startswith("/task "):
        return {"name": "create_task", "arguments": {"title": stripped[6:].strip(), "status": "open"}, "approved": True}
    if lowered.startswith("/search "):
        return {"name": "search_documents", "arguments": {"query": stripped[8:].strip()}, "approved": True}
    if lowered.startswith("/remember "):
        return {"name": "save_memory", "arguments": {"content": stripped[10:].strip()}, "approved": True}
    if lowered.startswith("remember that "):
        return {"name": "save_memory", "arguments": {"content": stripped[len("remember that ") :].strip()}, "approved": True}
    if lowered.startswith("/summarize "):
        return {"name": "summarize_document", "arguments": {"label": stripped[11:].strip()}, "approved": True}
    if lowered.startswith("/done "):
        return {
            "name": "update_task",
            "arguments": {"title": stripped[6:].strip(), "status": "completed"},
            "approved": True,
        }
    created = re.search(r"\b(?:create|add) a task(?: to| for|:)?\s+(.+)$", stripped, re.IGNORECASE)
    if created:
        return {
            "name": "create_task",
            "arguments": {"title": created.group(1).strip().rstrip("."), "status": "open"},
            "approved": True,
        }
    remembered = re.search(r"\bremember that\s+(.+)$", stripped, re.IGNORECASE)
    if remembered:
        return {"name": "save_memory", "arguments": {"content": remembered.group(1).strip()}, "approved": True}
    return None


def suggest_memory_text(text: str) -> str | None:
    if re.search(r"\bremember that\b", text, re.IGNORECASE) or text.strip().lower().startswith("/remember"):
        return None
    match = PREFERENCE_RE.search(text)
    if not match:
        return None
    suggestion = " ".join(match.group(0).split())
    return suggestion[:500]


def _stored_result(operation: ToolOperation) -> ToolResult:
    payload = operation.result or {}
    return ToolResult(
        status=operation.status,
        message=str(payload.get("message") or "Already recorded."),
        error_category=operation.error_category,
        resource_type=operation.resource_type,
        resource_id=str(operation.resource_id) if operation.resource_id else None,
        citations=list(payload.get("citations") or []),
        data=dict(payload.get("data") or {}),
        operation_id=str(operation.id),
    )


def _dump_result(result: ToolResult) -> dict:
    return {
        "message": result.message[:4000],
        "citations": result.citations[:8],
        "data": result.data,
    }


async def _find_operation(session: AsyncSession, user_id: uuid.UUID, key: str) -> ToolOperation | None:
    return await session.scalar(
        select(ToolOperation).where(ToolOperation.user_id == user_id, ToolOperation.idempotency_key == key)
    )


async def execute_tool(name: str, arguments: dict, ctx: ToolContext, *, resume: bool = False) -> ToolResult:
    spec = REGISTRY.get(name)
    if spec is None:
        return await _reject(ctx, name or "unknown", arguments, "unsupported_tool", "That action is not available.")
    try:
        parsed = spec.model.model_validate(arguments)
    except ValidationError:
        return await _reject(ctx, name, arguments, "invalid_arguments", "The action arguments are invalid.")

    if ctx.idempotency_key and not resume:
        existing = await _find_operation(ctx.session, ctx.user_id, ctx.idempotency_key)
        if existing is not None:
            return _stored_result(existing)

    if authorize_tool_call(consequential=spec.consequential, approved=ctx.approved) and not resume:
        operation = ToolOperation(
            user_id=ctx.user_id,
            tool_name=name,
            idempotency_key=ctx.idempotency_key,
            status="pending_approval",
            arguments=_safe_args(parsed),
            result={"message": "This action needs confirmation before it runs."},
        )
        ctx.session.add(operation)
        try:
            await ctx.session.flush()
        except IntegrityError:
            existing = await _find_operation(ctx.session, ctx.user_id, ctx.idempotency_key or "")
            if existing is not None:
                return _stored_result(existing)
            raise
        return ToolResult(
            status="pending_approval",
            message="This action needs confirmation before it runs.",
            operation_id=str(operation.id),
            data={"tool_name": name, "arguments": _safe_args(parsed)},
        )

    operation: ToolOperation | None = None
    if resume:
        operation = await ctx.session.get(ToolOperation, ctx.operation_id)
        if operation is None or operation.user_id != ctx.user_id:
            raise AppError("not_found", "Action not found.", 404)
        if operation.status == "succeeded":
            return _stored_result(operation)
        if operation.status != "pending_approval":
            raise AppError("invalid_state", "This action is no longer pending.", 409)
        try:
            parsed = spec.model.model_validate(operation.arguments or arguments)
        except ValidationError as exc:
            raise AppError("invalid_arguments", "The stored action is no longer valid.", 409) from exc

    try:
        result = await spec.handler(parsed, ctx)
    except AppError as exc:
        result = ToolResult(status="failed", message=exc.message, error_category=exc.code)

    if operation is None:
        operation = ToolOperation(
            user_id=ctx.user_id,
            tool_name=name,
            idempotency_key=ctx.idempotency_key,
            status=result.status,
            resource_type=result.resource_type,
            resource_id=uuid.UUID(result.resource_id) if result.resource_id else None,
            error_category=result.error_category,
            arguments=_safe_args(parsed),
            result=_dump_result(result),
        )
        ctx.session.add(operation)
        try:
            await ctx.session.flush()
        except IntegrityError:
            existing = await _find_operation(ctx.session, ctx.user_id, ctx.idempotency_key or "")
            if existing is not None:
                return _stored_result(existing)
            raise
    else:
        operation.status = result.status if result.status in {"succeeded", "failed", "rejected"} else "failed"
        operation.error_category = result.error_category
        operation.resource_type = result.resource_type
        operation.resource_id = uuid.UUID(result.resource_id) if result.resource_id else None
        operation.result = _dump_result(result)
        operation.arguments = _safe_args(parsed)
        await ctx.session.flush()
    result.operation_id = str(operation.id)
    return result


async def _reject(ctx: ToolContext, name: str, arguments: dict, category: str, message: str) -> ToolResult:
    operation = ToolOperation(
        user_id=ctx.user_id,
        tool_name=name[:64],
        idempotency_key=None,
        status="rejected",
        error_category=category,
        arguments={"keys": sorted(str(key) for key in arguments)[:20]} if isinstance(arguments, dict) else {},
        result={"message": message},
    )
    ctx.session.add(operation)
    await ctx.session.flush()
    return ToolResult(status="rejected", message=message, error_category=category, operation_id=str(operation.id))


def _safe_args(model: BaseModel) -> dict:
    raw = model.model_dump(mode="json")
    safe = {}
    for key, value in raw.items():
        if isinstance(value, str):
            safe[key] = value[:2000]
        else:
            safe[key] = value
    return safe


async def _search(args: SearchArgs, ctx: ToolContext) -> ToolResult:
    outcome = await retrieve_chunks(ctx.session, user_id=ctx.user_id, query=args.query, limit=5)
    if not outcome.chunks:
        return ToolResult(status="succeeded", message="No matching document evidence was found.", data={"count": 0})
    lines = []
    citations = []
    for index, chunk in enumerate(outcome.chunks, start=1):
        marker = f"S{index}"
        lines.append(f"{trim_text(chunk.content, 320)} [{marker}]")
        citations.append(
            {
                "marker": marker,
                "type": "document",
                "document_id": str(chunk.document_id),
                "chunk_id": str(chunk.chunk_id),
                "label": chunk.label,
                "filename": chunk.filename,
                "page_start": chunk.page_start,
                "excerpt": trim_text(chunk.content, 320),
            }
        )
    return ToolResult(
        status="succeeded",
        message="\n\n".join(lines),
        citations=citations,
        data={"count": len(outcome.chunks)},
    )


async def _create_task(args: CreateTaskArgs, ctx: ToolContext) -> ToolResult:
    from datetime import date

    due = None
    if args.due_date:
        try:
            due = date.fromisoformat(args.due_date)
        except ValueError as exc:
            raise AppError("invalid_arguments", "Due dates must use YYYY-MM-DD.") from exc
    if args.priority not in {None, "low", "medium", "high"}:
        raise AppError("invalid_arguments", "Priority must be low, medium, or high.")
    task, duplicate = await create_task(
        ctx.session,
        user_id=ctx.user_id,
        title=args.title,
        description=args.description,
        due_date=due,
        due_label=args.due_label,
        priority=args.priority,
        status=args.status if args.status in {"proposed", "open"} else "proposed",
        source_type="tool",
        idempotency_key=ctx.idempotency_key,
        invoked_by=ctx.invoked_by,
        allow_duplicate=False,
    )
    note = "That task already exists." if duplicate else "Task recorded."
    return ToolResult(
        status="succeeded",
        message=f"{note} {task.title} ({task.status}).",
        resource_type="task",
        resource_id=str(task.id),
        data={"duplicate": duplicate, "status": task.status, "title": task.title},
    )


async def _update_task(args: UpdateTaskArgs, ctx: ToolContext) -> ToolResult:
    if args.status not in {None, "proposed", "open", "completed", "cancelled"}:
        raise AppError("invalid_arguments", "That task status is not valid.")
    changes = {}
    if args.status:
        changes["status"] = args.status
    task = await update_task(
        ctx.session,
        user_id=ctx.user_id,
        task_id=args.task_id,
        title=args.title,
        changes=changes,
    )
    return ToolResult(
        status="succeeded",
        message=f"Updated “{task.title}” to {task.status}.",
        resource_type="task",
        resource_id=str(task.id),
        data={"status": task.status, "title": task.title},
    )


async def _list_tasks(args: ListTasksArgs, ctx: ToolContext) -> ToolResult:
    statement = select(Task).where(Task.user_id == ctx.user_id).order_by(Task.updated_at.desc()).limit(20)
    if args.status:
        statement = statement.where(Task.status == args.status)
    tasks = list(await ctx.session.scalars(statement))
    if not tasks:
        return ToolResult(status="succeeded", message="No tasks in that view.", data={"tasks": []})
    lines = [f"- {task.title} [{task.status}]" for task in tasks]
    return ToolResult(
        status="succeeded",
        message="\n".join(lines),
        data={"tasks": [{"id": str(task.id), "title": task.title, "status": task.status} for task in tasks]},
    )


async def _save_memory(args: MemoryArgs, ctx: ToolContext) -> ToolResult:
    memory, outcome = await create_memory(
        ctx.session,
        user_id=ctx.user_id,
        content=args.content,
        source="user" if ctx.invoked_by == "user" else "model_suggestion",
        invoked_by=ctx.invoked_by,
    )
    if memory.status != "active":
        message = "I saved this as a suggestion. It will not be used until you approve it."
    elif outcome == "duplicate":
        message = "That memory is already saved."
    else:
        message = "Saved to personal memory."
    return ToolResult(
        status="succeeded",
        message=message,
        resource_type="memory",
        resource_id=str(memory.id),
        data={"status": memory.status, "source": memory.source, "outcome": outcome},
    )


async def _retrieve_memories(args: RetrieveMemoryArgs, ctx: ToolContext) -> ToolResult:
    memories = await retrieve_memories(ctx.session, user_id=ctx.user_id, query=args.query, limit=5)
    if not memories:
        return ToolResult(status="succeeded", message="No active memories matched.", data={"count": 0})
    lines = [f"- ({memory.source}) {memory.content}" for memory in memories]
    return ToolResult(status="succeeded", message="\n".join(lines), data={"count": len(memories)})


async def _resolve_document(session: AsyncSession, user_id: uuid.UUID, args: SummarizeArgs) -> Document:
    if args.document_id is not None:
        document = await session.get(Document, args.document_id)
        if document is None or document.user_id != user_id:
            raise AppError("not_found", "Document not found.", 404)
        return document
    label = (args.label or "").strip()
    rows = list(
        await session.scalars(
            select(Document).where(
                Document.user_id == user_id,
                (Document.label.ilike(label)) | (Document.filename.ilike(label)),
            )
        )
    )
    if not rows:
        fuzzy = list(
            await session.scalars(
                select(Document).where(
                    Document.user_id == user_id,
                    (Document.label.ilike(f"%{label}%")) | (Document.filename.ilike(f"%{label}%")),
                )
            )
        )
        rows = fuzzy
    if not rows:
        raise AppError("not_found", "Document not found.", 404)
    if len(rows) > 1:
        raise AppError("ambiguous_document", "More than one document matches that label.", 409)
    return rows[0]


async def _summarize(args: SummarizeArgs, ctx: ToolContext) -> ToolResult:
    from app.models import DocumentChunk

    document = await _resolve_document(ctx.session, ctx.user_id, args)
    chunks = list(
        await ctx.session.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document.id, DocumentChunk.user_id == ctx.user_id)
            .order_by(DocumentChunk.chunk_index)
        )
    )
    if document.status != "completed" or not chunks:
        raise AppError("invalid_state", "This document is not ready to summarize.", 409)
    selected = chunks[:8]
    citations = []
    blocks = []
    for index, chunk in enumerate(selected, start=1):
        marker = f"S{index}"
        blocks.append(f"[{marker}] {trim_text(chunk.content, 500)}")
        citations.append(
            {
                "marker": marker,
                "type": "document",
                "document_id": str(document.id),
                "chunk_id": str(chunk.id),
                "label": document.label,
                "filename": document.filename,
                "page_start": chunk.page_start,
                "section": chunk.section,
                "excerpt": trim_text(chunk.content, 320),
            }
        )
    extractive = f"Summary of {document.label}, quoted from the indexed text.\n\n" + "\n\n".join(blocks)
    if settings.llm_configured:
        prompt = (
            "Summarize the document using only the evidence. Cite markers like [S1]. "
            "Do not add facts that are not present.\n\n" + "\n\n".join(blocks)
        )
        try:
            text, _usage = await generate_text(prompt)
            message = text
        except AppError:
            message = extractive
    else:
        message = extractive
    return ToolResult(
        status="succeeded",
        message=message,
        citations=citations,
        resource_type="document",
        resource_id=str(document.id),
    )


REGISTRY: dict[str, ToolSpec] = {}


def _register(spec: ToolSpec) -> None:
    REGISTRY[spec.name] = spec


_register(ToolSpec("search_documents", "Search the user's documents.", SearchArgs, False, _search))
_register(ToolSpec("retrieve_memories", "Retrieve active personal memories.", RetrieveMemoryArgs, False, _retrieve_memories))
_register(ToolSpec("create_task", "Create a task. Model calls stay proposed.", CreateTaskArgs, False, _create_task))
_register(ToolSpec("update_task", "Update a task. Status changes need user approval.", UpdateTaskArgs, True, _update_task))
_register(ToolSpec("list_tasks", "List the user's tasks.", ListTasksArgs, False, _list_tasks))
_register(ToolSpec("save_memory", "Save a memory. Model calls stay suggestions.", MemoryArgs, False, _save_memory))
_register(ToolSpec("summarize_document", "Summarize one owned document.", SummarizeArgs, False, _summarize))


async def confirm_operation(session: AsyncSession, user_id: uuid.UUID, operation_id: uuid.UUID) -> ToolResult:
    operation = await session.get(ToolOperation, operation_id)
    if operation is None or operation.user_id != user_id:
        raise AppError("not_found", "Action not found.", 404)
    ctx = ToolContext(
        session=session,
        user_id=user_id,
        invoked_by="user",
        approved=True,
        idempotency_key=operation.idempotency_key,
        operation_id=operation.id,
    )
    return await execute_tool(operation.tool_name, operation.arguments or {}, ctx, resume=True)


async def reject_operation(session: AsyncSession, user_id: uuid.UUID, operation_id: uuid.UUID) -> ToolOperation:
    operation = await session.get(ToolOperation, operation_id)
    if operation is None or operation.user_id != user_id:
        raise AppError("not_found", "Action not found.", 404)
    if operation.status != "pending_approval":
        raise AppError("invalid_state", "This action is no longer pending.", 409)
    operation.status = "rejected"
    operation.error_category = "rejected"
    operation.result = {"message": "The action was rejected."}
    operation.arguments = {}
    await session.flush()
    _ = utcnow()
    return operation
