import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.time import utcnow
from app.models import Task
from app.services.policies import forced_task_status, guard_due_date, guard_due_label
from app.services.textutil import normalize_title

ACTION_RE = re.compile(
    r"^\s*(?:[-*]|\d+[.)])\s+((?:complete|add|review|implement|fix|prepare|write|update|create|finish|ship|define|document|test)\b.+)$",
    re.IGNORECASE,
)
SENTENCE_RE = re.compile(
    r"^\s*((?:complete|add|review|implement|fix|prepare|write|update|create|finish|ship|define|document|test)\b.{8,180})$",
    re.IGNORECASE,
)
TODO_RE = re.compile(r"^\s*TODO:\s+(.+)$", re.IGNORECASE)
ISO_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
WEEKDAY_RE = re.compile(r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b", re.IGNORECASE)


@dataclass
class TaskDraft:
    title: str
    description: str
    due_date: date | None
    due_label: str | None
    priority: str | None
    source_excerpt: str
    confidence: float


def parse_due(text: str) -> tuple[date | None, str | None]:
    iso_match = ISO_RE.search(text)
    due_iso = None
    if iso_match:
        try:
            date.fromisoformat(iso_match.group(1))
            due_iso = iso_match.group(1)
        except ValueError:
            due_iso = None
    weekday = WEEKDAY_RE.search(text)
    label = weekday.group(1) if weekday and due_iso is None else None
    due_iso = guard_due_date(due_iso, text, text)
    label = guard_due_label(label, text)
    return (date.fromisoformat(due_iso) if due_iso else None), label


def priority_from_text(text: str) -> str | None:
    lowered = text.lower()
    if "high priority" in lowered or "urgent" in lowered:
        return "high"
    if "low priority" in lowered:
        return "low"
    if "medium priority" in lowered:
        return "medium"
    return None


def extract_task_drafts(text: str) -> list[TaskDraft]:
    drafts: list[TaskDraft] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        match = ACTION_RE.match(raw_line) or TODO_RE.match(raw_line) or SENTENCE_RE.match(raw_line)
        if not match:
            continue
        body = " ".join(match.group(1).split())
        title = body[:200].strip(" .")
        normalized = normalize_title(title)
        if len(normalized) < 3 or normalized in seen:
            continue
        seen.add(normalized)
        due_date, due_label = parse_due(body)
        drafts.append(
            TaskDraft(
                title=title,
                description="",
                due_date=due_date,
                due_label=due_label,
                priority=priority_from_text(body),
                source_excerpt=body[:500],
                confidence=0.55,
            )
        )
    return drafts


def extraction_key(user_id: uuid.UUID, source_type: str | None, source_id: uuid.UUID | None, normalized: str) -> str:
    raw = f"{user_id}:{source_type or ''}:{source_id or ''}:{normalized}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:80]


async def _existing_duplicate(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    normalized: str,
    idempotency_key: str | None,
) -> Task | None:
    if idempotency_key:
        existing = await session.scalar(
            select(Task).where(Task.user_id == user_id, Task.idempotency_key == idempotency_key)
        )
        if existing is not None:
            return existing
    return await session.scalar(
        select(Task).where(
            Task.user_id == user_id,
            Task.normalized_title == normalized,
            Task.status.in_(("proposed", "open", "completed")),
        )
    )


async def create_task(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    title: str,
    description: str = "",
    due_date: date | None = None,
    due_label: str | None = None,
    priority: str | None = None,
    status: str = "proposed",
    source_type: str | None = None,
    source_id: uuid.UUID | None = None,
    source_excerpt: str | None = None,
    confidence: float | None = None,
    idempotency_key: str | None = None,
    invoked_by: str = "user",
    allow_duplicate: bool = False,
) -> tuple[Task, bool]:
    cleaned = " ".join(title.split()).strip()
    if len(cleaned) < 3:
        raise AppError("invalid_arguments", "A task title needs at least 3 characters.")
    normalized = normalize_title(cleaned)
    due_iso = guard_due_date(due_date.isoformat() if due_date else None, f"{cleaned}\n{source_excerpt or ''}", source_excerpt)
    safe_due = date.fromisoformat(due_iso) if due_iso else None
    safe_label = guard_due_label(due_label, f"{cleaned}\n{source_excerpt or ''}")
    safe_status = forced_task_status(invoked_by, status)
    if idempotency_key is None and source_id is not None:
        idempotency_key = extraction_key(user_id, source_type, source_id, normalized)
    if not allow_duplicate:
        existing = await _existing_duplicate(
            session, user_id=user_id, normalized=normalized, idempotency_key=idempotency_key
        )
        if existing is not None:
            return existing, True
    task = Task(
        user_id=user_id,
        title=cleaned[:200],
        description=description[:4000],
        due_date=safe_due,
        due_label=safe_label[:80] if safe_label else None,
        priority=priority,
        status=safe_status,
        source_type=source_type,
        source_id=source_id,
        source_excerpt=(source_excerpt or None) and source_excerpt[:500],
        confidence=confidence,
        idempotency_key=idempotency_key,
        normalized_title=normalized,
    )
    try:
        async with session.begin_nested():
            session.add(task)
            await session.flush()
    except IntegrityError:
        existing = await _existing_duplicate(
            session, user_id=user_id, normalized=normalized, idempotency_key=idempotency_key
        )
        if existing is not None:
            return existing, True
        raise
    return task, False


async def save_extracted_tasks(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    drafts: list[TaskDraft],
    source_type: str,
    source_id: uuid.UUID,
    source_text: str,
    invoked_by: str = "model",
) -> list[tuple[Task, bool]]:
    saved: list[tuple[Task, bool]] = []
    for draft in drafts:
        due_iso = guard_due_date(draft.due_date.isoformat() if draft.due_date else None, source_text, draft.source_excerpt)
        due = date.fromisoformat(due_iso) if due_iso else None
        task, duplicate = await create_task(
            session,
            user_id=user_id,
            title=draft.title,
            description=draft.description,
            due_date=due,
            due_label=guard_due_label(draft.due_label, source_text),
            priority=draft.priority,
            status="proposed",
            source_type=source_type,
            source_id=source_id,
            source_excerpt=draft.source_excerpt,
            confidence=draft.confidence,
            invoked_by=invoked_by,
        )
        saved.append((task, duplicate))
    return saved


async def get_owned_task(session: AsyncSession, user_id: uuid.UUID, task_id: uuid.UUID) -> Task:
    task = await session.get(Task, task_id)
    if task is None or task.user_id != user_id:
        raise AppError("not_found", "Task not found.", 404)
    return task


async def update_task(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    task_id: uuid.UUID | None,
    title: str | None,
    changes: dict,
) -> Task:
    if task_id is not None:
        task = await get_owned_task(session, user_id, task_id)
    elif title:
        normalized = normalize_title(title)
        matches = list(
            await session.scalars(select(Task).where(Task.user_id == user_id, Task.normalized_title == normalized))
        )
        if not matches:
            raise AppError("not_found", "Task not found.", 404)
        if len(matches) > 1:
            raise AppError("ambiguous_task", "More than one task matches that title.", 409)
        task = matches[0]
    else:
        raise AppError("invalid_arguments", "A task id or title is required.")
    if "title" in changes and changes["title"]:
        task.title = " ".join(changes["title"].split())[:200]
        task.normalized_title = normalize_title(task.title)
    if "description" in changes and changes["description"] is not None:
        task.description = changes["description"][:4000]
    if "status" in changes and changes["status"]:
        task.status = changes["status"]
    if "priority" in changes:
        task.priority = changes["priority"]
    if "due_date" in changes:
        task.due_date = changes["due_date"]
    if "due_label" in changes:
        task.due_label = changes["due_label"]
    task.updated_at = utcnow()
    await session.flush()
    return task
