import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditEvent, Conversation, Document, Memory, Message, Task, User
from app.serializers import conversation_to_dict, document_to_dict, memory_to_dict, task_to_dict, user_to_dict

ACTIVITY_TEXT = {
    "document_uploaded": "Uploaded a document",
    "document_processed": "Finished processing a document",
    "document_failed": "Document processing failed",
    "document_deleted": "Deleted a document",
    "conversation_created": "Started a conversation",
    "task_created": "Recorded a task",
    "memory_saved": "Saved a memory",
    "account_deleted": "Deleted the account",
    "login": "Signed in",
}


async def dashboard_for(session: AsyncSession, user: User) -> dict:
    user_id = user.id
    documents = await _count(session, Document, user_id)
    conversations = await _count(session, Conversation, user_id)
    memories = await session.scalar(
        select(func.count()).select_from(Memory).where(Memory.user_id == user_id, Memory.status == "active")
    )
    open_tasks = await session.scalar(
        select(func.count()).select_from(Task).where(Task.user_id == user_id, Task.status.in_(("proposed", "open")))
    )
    recent_conversations = list(
        await session.scalars(
            select(Conversation)
            .where(Conversation.user_id == user_id, Conversation.archived_at.is_(None))
            .order_by(Conversation.updated_at.desc())
            .limit(5)
        )
    )
    recent_documents = list(
        await session.scalars(
            select(Document).where(Document.user_id == user_id).order_by(Document.created_at.desc()).limit(5)
        )
    )
    processing = list(
        await session.scalars(
            select(Document)
            .where(Document.user_id == user_id, Document.status.in_(("queued", "processing", "failed")))
            .order_by(Document.updated_at.desc())
            .limit(6)
        )
    )
    recent_memories = list(
        await session.scalars(
            select(Memory)
            .where(Memory.user_id == user_id, Memory.status == "active")
            .order_by(Memory.updated_at.desc())
            .limit(4)
        )
    )
    pending_tasks = list(
        await session.scalars(
            select(Task)
            .where(Task.user_id == user_id, Task.status.in_(("proposed", "open")))
            .order_by(Task.updated_at.desc())
            .limit(6)
        )
    )
    events = list(
        await session.scalars(
            select(AuditEvent).where(AuditEvent.user_id == user_id).order_by(AuditEvent.created_at.desc()).limit(12)
        )
    )
    return {
        "user": user_to_dict(user),
        "counts": {
            "documents": documents,
            "conversations": conversations,
            "memories": int(memories or 0),
            "open_tasks": int(open_tasks or 0),
        },
        "recent_conversations": [conversation_to_dict(item) for item in recent_conversations],
        "documents": [document_to_dict(item) for item in recent_documents],
        "processing": [document_to_dict(item) for item in processing],
        "memories": [memory_to_dict(item) for item in recent_memories],
        "pending_tasks": [task_to_dict(item) for item in pending_tasks],
        "activity": [_activity(event) for event in events],
    }


async def _count(session: AsyncSession, model, user_id: uuid.UUID) -> int:
    value = await session.scalar(select(func.count()).select_from(model).where(model.user_id == user_id))
    return int(value or 0)


def _activity(event: AuditEvent) -> dict:
    details = event.details or {}
    label = details.get("filename") or details.get("label") or details.get("title")
    summary = ACTIVITY_TEXT.get(event.action, event.action.replace("_", " "))
    if label:
        summary = f"{summary}: {label}"
    return {
        "id": str(event.id),
        "action": event.action,
        "summary": summary,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


async def activity_counts(session: AsyncSession, user_id: uuid.UUID) -> dict:
    messages = await session.scalar(select(func.count()).select_from(Message).where(Message.user_id == user_id))
    return {"messages": int(messages or 0)}
