from app.models import (
    Conversation,
    Document,
    EvaluationRun,
    Memory,
    Message,
    Task,
    ToolOperation,
    User,
)

PUBLIC_DIAGNOSTIC_KEYS = {
    "retrieved_count",
    "selected_count",
    "retrieval_ms",
    "generation_ms",
    "insufficient_support",
    "embedding_provider",
    "llm_provider",
    "selected_source_ids",
    "selected_scores",
    "mode",
    "tool_name",
}


def _iso(value) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def public_diagnostics(diagnostics: dict | None) -> dict:
    raw = diagnostics or {}
    return {key: raw[key] for key in PUBLIC_DIAGNOSTIC_KEYS if key in raw}


def user_to_dict(user: User) -> dict:
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "timezone": user.timezone,
        "preferred_language": user.preferred_language,
        "response_style": user.response_style,
        "memory_enabled": user.memory_enabled,
        "email_verified": user.email_verified_at is not None,
        "created_at": _iso(user.created_at),
    }


def conversation_to_dict(conversation: Conversation) -> dict:
    return {
        "id": str(conversation.id),
        "title": conversation.title,
        "archived_at": _iso(conversation.archived_at),
        "created_at": _iso(conversation.created_at),
        "updated_at": _iso(conversation.updated_at),
    }


def message_to_dict(message: Message) -> dict:
    return {
        "id": str(message.id),
        "conversation_id": str(message.conversation_id),
        "role": message.role,
        "content": message.content,
        "status": message.status,
        "citations": message.citations or [],
        "evidence": message.evidence or [],
        "actions": message.actions or [],
        "diagnostics": public_diagnostics(message.diagnostics),
        "usage": message.usage or {},
        "error_code": message.error_code,
        "created_at": _iso(message.created_at),
    }


def document_to_dict(document: Document) -> dict:
    return {
        "id": str(document.id),
        "filename": document.filename,
        "label": document.label,
        "mime_type": document.mime_type,
        "extension": document.extension,
        "size_bytes": document.size_bytes,
        "status": document.status,
        "error_code": document.error_code,
        "error_message": document.error_message,
        "page_count": document.page_count,
        "chunk_count": document.chunk_count,
        "cancel_requested": document.cancel_requested,
        "created_at": _iso(document.created_at),
        "updated_at": _iso(document.updated_at),
    }


def memory_to_dict(memory: Memory) -> dict:
    return {
        "id": str(memory.id),
        "content": memory.content,
        "source": memory.source,
        "status": memory.status,
        "conflict_with_id": str(memory.conflict_with_id) if memory.conflict_with_id else None,
        "version": memory.version,
        "created_at": _iso(memory.created_at),
        "updated_at": _iso(memory.updated_at),
    }


def task_to_dict(task: Task, *, duplicate: bool = False) -> dict:
    return {
        "id": str(task.id),
        "title": task.title,
        "description": task.description,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "due_label": task.due_label,
        "priority": task.priority,
        "status": task.status,
        "source_type": task.source_type,
        "source_id": str(task.source_id) if task.source_id else None,
        "source_excerpt": task.source_excerpt,
        "confidence": task.confidence,
        "duplicate": duplicate,
        "created_at": _iso(task.created_at),
        "updated_at": _iso(task.updated_at),
    }


def run_to_dict(run: EvaluationRun) -> dict:
    return {
        "id": str(run.id),
        "dataset_id": str(run.dataset_id),
        "status": run.status,
        "config": run.config or {},
        "metrics": run.metrics or {},
        "error_code": run.error_code,
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
        "created_at": _iso(run.created_at),
    }


def operation_to_dict(operation: ToolOperation) -> dict:
    return {
        "id": str(operation.id),
        "tool_name": operation.tool_name,
        "status": operation.status,
        "resource_type": operation.resource_type,
        "resource_id": str(operation.resource_id) if operation.resource_id else None,
        "error_category": operation.error_category,
        "created_at": _iso(operation.created_at),
    }
