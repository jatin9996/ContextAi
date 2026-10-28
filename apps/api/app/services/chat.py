import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable

from sqlalchemy import select

from app.core.config import settings
from app.core.errors import AppError
from app.core.time import utcnow
from app.db.session import SessionLocal
from app.models import Conversation, Message, User
from app.serializers import message_to_dict
from app.services.embeddings import get_embeddings
from app.services.llm import generate_text
from app.services.rag import fallback_answer, finalize_answer, prepare_grounding
from app.services.retrieval import retrieve_chunks, retrieve_memories
from app.services.textutil import build_search_query, title_from_message
from app.services.tools import ToolContext, execute_tool, parse_user_command, suggest_memory_text


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


async def _emit_words(text: str, on_token: Callable[[str], Awaitable[None]]) -> None:
    words = text.split(" ")
    buffer: list[str] = []
    for word in words:
        buffer.append(word)
        if len(buffer) >= 8:
            await on_token(" ".join(buffer) + " ")
            buffer = []
    if buffer:
        await on_token(" ".join(buffer))


async def answer_question(
    *,
    user_id: uuid.UUID,
    question: str,
    history: list[tuple[str, str]],
    on_token: Callable[[str], Awaitable[None]] | None = None,
) -> dict:
    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        if user is None:
            raise AppError("unauthorized", "Authentication is required.", 401)
        response_style = user.response_style
        language = user.preferred_language
        memory_enabled = user.memory_enabled
        outcome = await retrieve_chunks(session, user_id=user_id, query=question)
        memories = await retrieve_memories(session, user_id=user_id, query=question) if memory_enabled else []
        provider = get_embeddings().provider
        grounding = prepare_grounding(
            query=question,
            chunks=outcome.chunks,
            memories=memories,
            history=history,
            response_style=response_style,
            language=language,
            embedding_provider=provider,
            llm_configured=settings.llm_configured,
        )
        retrieval_ms = round(outcome.latency_ms, 2)
        retrieved_count = outcome.retrieved_count
    started = time.perf_counter()
    usage: dict = {}
    llm_provider = "none"
    if grounding.mode != "abstain" and settings.llm_configured:
        try:
            text, usage = await asyncio.wait_for(
                generate_text(grounding.prompt, on_token=on_token),
                timeout=settings.llm_timeout_seconds,
            )
        except TimeoutError as exc:
            raise AppError("model_timeout", "The model took too long to respond.", 504) from exc
        llm_provider = "gemini"
    else:
        text = fallback_answer(grounding)
        if on_token is not None:
            await _emit_words(text, on_token)
    final_text, citations, insufficient = finalize_answer(text, grounding)
    evidence = [] if insufficient else grounding.evidence
    return {
        "content": final_text,
        "citations": citations,
        "evidence": evidence,
        "actions": [],
        "usage": usage,
        "diagnostics": {
            "retrieved_count": retrieved_count,
            "selected_count": len(grounding.labeled_chunks),
            "retrieval_ms": retrieval_ms,
            "generation_ms": round((time.perf_counter() - started) * 1000, 2),
            "insufficient_support": insufficient,
            "embedding_provider": provider,
            "llm_provider": llm_provider,
            "selected_source_ids": [item["chunk_id"] for item in grounding.evidence if item.get("type") == "document"],
            "selected_scores": [
                {"chunk_id": item.get("chunk_id") or item.get("memory_id"), "score": item.get("score")}
                for item in grounding.evidence
            ],
            "mode": grounding.mode,
        },
    }


async def _set_message(message_id: uuid.UUID, **values) -> None:
    async with SessionLocal() as session:
        async with session.begin():
            message = await session.get(Message, message_id)
            if message is None:
                return
            if values.get("status") == "incomplete" and message.status != "streaming":
                return
            for key, value in values.items():
                setattr(message, key, value)


async def stream_reply(
    *,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    content: str,
    idempotency_key: str | None,
) -> AsyncIterator[str]:
    assistant_id: uuid.UUID | None = None
    terminal = False
    background: asyncio.Task | None = None
    try:
        async with SessionLocal() as session:
            async with session.begin():
                conversation = await session.get(Conversation, conversation_id)
                if conversation is None or conversation.user_id != user_id:
                    raise AppError("not_found", "Conversation not found.", 404)
                if idempotency_key:
                    existing = await session.scalar(
                        select(Message).where(
                            Message.conversation_id == conversation_id,
                            Message.idempotency_key == idempotency_key,
                            Message.role == "user",
                        )
                    )
                    if existing is not None:
                        assistant = await session.scalar(
                            select(Message)
                            .where(
                                Message.conversation_id == conversation_id,
                                Message.role == "assistant",
                                Message.created_at >= existing.created_at,
                            )
                            .order_by(Message.created_at)
                        )
                        if assistant is not None and assistant.status == "streaming":
                            yield sse("error", {"code": "conflict", "message": "This message is already being answered."})
                            terminal = True
                            return
                        if assistant is not None:
                            yield sse("done", {"message": message_to_dict(assistant)})
                            terminal = True
                            return
                previous = await session.scalar(
                    select(Message)
                    .where(Message.conversation_id == conversation_id, Message.role == "user")
                    .order_by(Message.created_at.desc())
                )
                history_rows = list(
                    await session.scalars(
                        select(Message)
                        .where(Message.conversation_id == conversation_id, Message.status == "completed")
                        .order_by(Message.created_at.desc())
                        .limit(6)
                    )
                )
                history = [(row.role, row.content) for row in reversed(history_rows) if row.content]
                user_message = Message(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    role="user",
                    content=content,
                    status="completed",
                    idempotency_key=idempotency_key,
                )
                assistant = Message(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    role="assistant",
                    content="",
                    status="streaming",
                )
                if conversation.title == "New conversation":
                    conversation.title = title_from_message(content)
                conversation.archived_at = None
                conversation.updated_at = utcnow()
                session.add(user_message)
                session.add(assistant)
                await session.flush()
                assistant_id = assistant.id
                previous_text = previous.content if previous else None
                yield_user = message_to_dict(user_message)
        yield sse("user", {"message": yield_user})

        command = parse_user_command(content)
        if command is not None:
            async with SessionLocal() as session:
                async with session.begin():
                    result = await execute_tool(
                        command["name"],
                        command["arguments"],
                        ToolContext(
                            session=session,
                            user_id=user_id,
                            invoked_by="user",
                            approved=bool(command["approved"]),
                            idempotency_key=f"msg:{assistant_id}:{command['name']}",
                        ),
                    )
            actions = []
            if result.status == "pending_approval":
                actions.append(
                    {
                        "type": "confirm_action",
                        "operation_id": result.operation_id,
                        "tool_name": command["name"],
                        "summary": result.message,
                    }
                )
            payload = {
                "content": result.message,
                "citations": result.citations,
                "evidence": result.citations,
                "actions": actions,
                "usage": {},
                "diagnostics": {"tool_name": command["name"], "mode": "tool", "insufficient_support": False},
            }
        else:
            queue: asyncio.Queue = asyncio.Queue()

            async def on_token(piece: str) -> None:
                await queue.put(("token", piece))

            async def run_answer() -> None:
                try:
                    query = build_search_query(content, previous_text)
                    result = await answer_question(
                        user_id=user_id,
                        question=query,
                        history=history,
                        on_token=on_token,
                    )
                    suggestion = suggest_memory_text(content)
                    async with SessionLocal() as session:
                        user = await session.get(User, user_id)
                        if suggestion and user is not None and user.memory_enabled:
                            result["actions"] = [
                                {"type": "memory_suggestion", "content": suggestion, "source": "user"}
                            ]
                    await queue.put(("result", result))
                except Exception as exc:
                    await queue.put(("error", exc))
                finally:
                    await queue.put(None)

            background = asyncio.create_task(run_answer())
            payload = None
            while True:
                item = await queue.get()
                if item is None:
                    break
                kind, value = item
                if kind == "token":
                    yield sse("token", {"text": value})
                elif kind == "error":
                    raise value
                elif kind == "result":
                    payload = value
            await background
            background = None
            if payload is None:
                raise AppError("empty_response", "The assistant did not produce a response.", 502)

        if command is not None:
            words = payload["content"].split(" ")
            buffer: list[str] = []
            for word in words:
                buffer.append(word)
                if len(buffer) >= 8:
                    yield sse("token", {"text": " ".join(buffer) + " "})
                    buffer = []
            if buffer:
                yield sse("token", {"text": " ".join(buffer)})

        async with SessionLocal() as session:
            async with session.begin():
                assistant = await session.get(Message, assistant_id)
                if assistant is None:
                    raise AppError("not_found", "Conversation not found.", 404)
                assistant.content = payload["content"]
                assistant.citations = payload["citations"]
                assistant.evidence = payload["evidence"]
                assistant.actions = payload["actions"]
                assistant.diagnostics = payload["diagnostics"]
                assistant.usage = payload["usage"]
                assistant.status = "completed"
                assistant.error_code = None
                done = message_to_dict(assistant)
        terminal = True
        yield sse("done", {"message": done})
    except AppError as exc:
        terminal = True
        if assistant_id is not None:
            await _set_message(assistant_id, status="failed", error_code=exc.code, content="")
        yield sse("error", {"code": exc.code, "message": exc.message})
    except Exception:
        terminal = True
        if assistant_id is not None:
            await _set_message(assistant_id, status="failed", error_code="generation_failed", content="")
        yield sse("error", {"code": "generation_failed", "message": "The assistant could not finish this response."})
    finally:
        if background is not None:
            background.cancel()
        if assistant_id is not None and not terminal:
            await _set_message(assistant_id, status="incomplete", error_code="interrupted")

