import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.time import utcnow
from app.models import Memory, MemoryEmbedding
from app.services.embeddings import get_embeddings
from app.services.policies import classify_memory_overlap, forced_memory_status, memory_jaccard


async def _recent_memories(session: AsyncSession, user_id: uuid.UUID) -> list[Memory]:
    rows = await session.scalars(
        select(Memory)
        .where(Memory.user_id == user_id, Memory.status.in_(("active", "suggested", "conflict_pending")))
        .order_by(Memory.updated_at.desc())
        .limit(30)
    )
    return list(rows)


async def create_memory(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    content: str,
    source: str = "user",
    invoked_by: str = "user",
    confirm_conflicts: bool = False,
) -> tuple[Memory, str]:
    cleaned = " ".join(content.split()).strip()
    if len(cleaned) < 3:
        raise AppError("invalid_arguments", "Memory content is too short.")
    if len(cleaned) > 4000:
        raise AppError("invalid_arguments", "Memory content is too long.")
    status = forced_memory_status(source=source, invoked_by=invoked_by, requested="active")
    duplicate: Memory | None = None
    conflict: Memory | None = None
    for existing in await _recent_memories(session, user_id):
        relation = classify_memory_overlap(memory_jaccard(cleaned, existing.content), None)
        if relation == "duplicate":
            duplicate = existing
            break
        if relation == "conflict" and conflict is None and existing.status == "active":
            conflict = existing
    if duplicate is not None:
        return duplicate, "duplicate"
    if conflict is not None and status == "active" and not confirm_conflicts:
        status = "conflict_pending"
    elif conflict is not None and status == "active" and confirm_conflicts:
        conflict.status = "superseded"
        conflict.updated_at = utcnow()
    memory = Memory(
        user_id=user_id,
        content=cleaned,
        source="model_suggestion" if invoked_by == "model" else source,
        status=status,
        conflict_with_id=conflict.id if conflict is not None and status == "conflict_pending" else None,
    )
    session.add(memory)
    await session.flush()
    vector = (await get_embeddings().embed([cleaned]))[0]
    session.add(MemoryEmbedding(memory_id=memory.id, user_id=user_id, embedding=vector))
    await session.flush()
    return memory, "created"


async def update_memory(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    memory_id: uuid.UUID,
    content: str | None,
    status: str | None,
) -> Memory:
    memory = await session.get(Memory, memory_id)
    if memory is None or memory.user_id != user_id:
        raise AppError("not_found", "Memory not found.", 404)
    if content is not None:
        cleaned = " ".join(content.split()).strip()
        if len(cleaned) < 3:
            raise AppError("invalid_arguments", "Memory content is too short.")
        memory.content = cleaned[:4000]
        memory.version += 1
        memory.updated_at = utcnow()
        vector = (await get_embeddings().embed([memory.content]))[0]
        embedding = await session.get(MemoryEmbedding, memory.id)
        if embedding is None:
            session.add(MemoryEmbedding(memory_id=memory.id, user_id=user_id, embedding=vector))
        else:
            embedding.embedding = vector
    if status is not None:
        if status not in {"active", "rejected", "suggested"}:
            raise AppError("invalid_arguments", "That memory status is not valid.")
        memory.status = status
        memory.updated_at = utcnow()
    await session.flush()
    return memory


async def resolve_memory(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    memory_id: uuid.UUID,
    action: str,
) -> Memory:
    memory = await session.get(Memory, memory_id)
    if memory is None or memory.user_id != user_id:
        raise AppError("not_found", "Memory not found.", 404)
    if action == "keep_new":
        memory.status = "active"
        if memory.conflict_with_id:
            other = await session.get(Memory, memory.conflict_with_id)
            if other is not None and other.user_id == user_id:
                other.status = "superseded"
                other.updated_at = utcnow()
    elif action == "keep_existing":
        memory.status = "rejected"
    else:
        raise AppError("invalid_arguments", "Choose keep_new or keep_existing.")
    memory.updated_at = utcnow()
    await session.flush()
    return memory


async def delete_memory(session: AsyncSession, *, user_id: uuid.UUID, memory_id: uuid.UUID) -> None:
    memory = await session.get(Memory, memory_id)
    if memory is None or memory.user_id != user_id:
        raise AppError("not_found", "Memory not found.", 404)
    await session.delete(memory)
    await session.flush()
