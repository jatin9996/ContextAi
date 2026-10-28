import uuid

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, enforce_rate, require_user
from app.core.errors import AppError
from app.core.time import utcnow
from app.db.session import get_session
from app.models import Conversation, Message
from app.schemas.contracts import ConversationCreate, ConversationUpdate, MessageCreate
from app.serializers import conversation_to_dict, message_to_dict
from app.services.audit import record_audit
from app.services.chat import stream_reply

router = APIRouter(prefix="/conversations", tags=["conversations"])


async def _owned(session: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID) -> Conversation:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user_id:
        raise AppError("not_found", "Conversation not found.", 404)
    return conversation


@router.post("", status_code=201)
async def create_conversation(
    body: ConversationCreate,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    title = (body.title or "New conversation").strip() or "New conversation"
    conversation = Conversation(user_id=user.id, title=title[:160])
    session.add(conversation)
    await session.flush()
    await record_audit(
        session,
        user_id=user.id,
        action="conversation_created",
        resource_type="conversation",
        resource_id=conversation.id,
        metadata={"title": conversation.title},
    )
    return conversation_to_dict(conversation)


@router.get("")
async def list_conversations(
    include_archived: bool = False,
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    filters = [Conversation.user_id == user.id]
    if not include_archived:
        filters.append(Conversation.archived_at.is_(None))
    total = await session.scalar(select(func.count()).select_from(Conversation).where(*filters))
    rows = await session.scalars(
        select(Conversation).where(*filters).order_by(Conversation.updated_at.desc()).limit(limit).offset(offset)
    )
    return {"items": [conversation_to_dict(row) for row in rows], "total": int(total or 0)}


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: uuid.UUID,
    before: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    conversation = await _owned(session, user.id, conversation_id)
    statement = select(Message).where(Message.conversation_id == conversation.id, Message.user_id == user.id)
    if before is not None:
        anchor = await session.get(Message, before)
        if anchor is None or anchor.conversation_id != conversation.id or anchor.user_id != user.id:
            raise AppError("not_found", "Message not found.", 404)
        statement = statement.where(tuple_(Message.created_at, Message.id) < tuple_(anchor.created_at, anchor.id))
    rows = list(await session.scalars(statement.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit + 1)))
    has_more = len(rows) > limit
    selected = list(reversed(rows[:limit]))
    return {
        "conversation": conversation_to_dict(conversation),
        "messages": [message_to_dict(row) for row in selected],
        "has_more": has_more,
    }


@router.patch("/{conversation_id}")
async def update_conversation(
    conversation_id: uuid.UUID,
    body: ConversationUpdate,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    conversation = await _owned(session, user.id, conversation_id)
    if body.title is not None:
        conversation.title = body.title.strip()[:160]
    if body.archived is True:
        conversation.archived_at = utcnow()
    elif body.archived is False:
        conversation.archived_at = None
    conversation.updated_at = utcnow()
    return conversation_to_dict(conversation)


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    conversation = await _owned(session, user.id, conversation_id)
    await session.delete(conversation)
    return {"message": "Conversation deleted."}


@router.post("/{conversation_id}/messages")
async def send_message(
    conversation_id: uuid.UUID,
    body: MessageCreate,
    user: CurrentUser = Depends(require_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    enforce_rate(f"message:{user.id}", limit=30, window_seconds=60)
    if idempotency_key and len(idempotency_key) > 80:
        raise AppError("invalid_arguments", "Idempotency-Key is too long.")
    generator = stream_reply(
        user_id=user.id,
        conversation_id=conversation_id,
        content=body.content,
        idempotency_key=idempotency_key,
    )
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
