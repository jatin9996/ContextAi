import json
from pathlib import Path

import pytest

from app.services.worker import process_next_job

pytestmark = pytest.mark.usefixtures("database_ready")


def _events(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.split("\n\n"):
        event = "message"
        data = ""
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data += line.split(":", 1)[1].strip()
        if data:
            events.append((event, json.loads(data)))
    return events


async def _register(client, email: str):
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Correct-horse-1", "display_name": "Avery"},
    )
    assert response.status_code == 201, response.text
    return response.json()["user"]


async def test_register_login_and_expired_session(client):
    await _register(client, "avery@example.com")
    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200
    logout = await client.post("/api/v1/auth/logout")
    assert logout.status_code == 200
    denied = await client.get("/api/v1/auth/me")
    assert denied.status_code == 401
    logged_in = await client.post(
        "/api/v1/auth/login",
        json={"email": "avery@example.com", "password": "Correct-horse-1"},
    )
    assert logged_in.status_code == 200
    from datetime import timedelta

    from sqlalchemy import update

    from app.core.time import utcnow
    from app.db.session import SessionLocal
    from app.models import Session

    async with SessionLocal() as session:
        async with session.begin():
            await session.execute(update(Session).values(expires_at=utcnow() - timedelta(minutes=5)))
    expired = await client.get("/api/v1/auth/me")
    assert expired.status_code == 401
    assert expired.json()["error"]["code"] == "session_expired"


async def test_users_cannot_read_each_others_documents_and_processing_is_idempotent(client):
    await _register(client, "owner@example.com")
    sample = Path(__file__).resolve().parents[4] / "samples" / "project-brief.md"
    upload = await client.post(
        "/api/v1/documents",
        files={"file": ("project-brief.md", sample.read_bytes(), "text/markdown")},
    )
    assert upload.status_code == 201, upload.text
    document_id = upload.json()["id"]
    assert await process_next_job("test-worker")
    status = await client.get(f"/api/v1/documents/{document_id}/status")
    assert status.json()["status"] == "completed"
    first_count = status.json()["chunk_count"]
    assert first_count > 0

    from uuid import UUID

    from sqlalchemy import update

    from app.db.session import SessionLocal
    from app.models import Document
    from app.services.processing import process_document

    async with SessionLocal() as session:
        async with session.begin():
            await session.execute(update(Document).where(Document.id == UUID(document_id)).values(status="queued"))
    assert await process_document(UUID(document_id)) == "completed"
    recounted = await client.get(f"/api/v1/documents/{document_id}/status")
    assert recounted.json()["chunk_count"] == first_count
    search = await client.post("/api/v1/search", json={"query": "SPEC-CTX-1842"})
    assert search.status_code == 200
    assert any(group["document_id"] == document_id for group in search.json()["groups"])

    await client.post("/api/v1/auth/logout")
    await _register(client, "other@example.com")
    hidden = await client.get(f"/api/v1/documents/{document_id}")
    assert hidden.status_code == 404
    hidden_file = await client.get(f"/api/v1/documents/{document_id}/file")
    assert hidden_file.status_code == 404


async def test_chat_cites_evidence_and_abstains(client):
    await _register(client, "chat@example.com")
    sample = Path(__file__).resolve().parents[4] / "samples" / "project-brief.md"
    upload = await client.post(
        "/api/v1/documents",
        files={"file": ("project-brief.md", sample.read_bytes(), "text/markdown")},
    )
    document_id = upload.json()["id"]
    assert await process_next_job("test-worker")
    ready = await client.get(f"/api/v1/documents/{document_id}/status")
    assert ready.json()["status"] == "completed"
    created = await client.post("/api/v1/conversations", json={})
    conversation_id = created.json()["id"]
    answer = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "What is the specification code?"},
    )
    events = _events(answer.text)
    done = next(payload for event, payload in events if event == "done")
    assert done["message"]["status"] == "completed"
    assert any(citation["type"] == "document" for citation in done["message"]["citations"])
    assert "SPEC-CTX-1842" in done["message"]["content"]

    abstained = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "Who operates the lunar pager relay?"},
    )
    abstain_done = next(payload for event, payload in _events(abstained.text) if event == "done")
    assert abstain_done["message"]["citations"] == []
    assert "do not establish" in abstain_done["message"]["content"].lower()
    again = await client.get(f"/api/v1/conversations/{conversation_id}")
    assert len(again.json()["messages"]) >= 4


async def test_task_idempotency_memory_deletion_and_sample_evaluation(client):
    await _register(client, "eval@example.com")
    created = await client.post(
        "/api/v1/tasks",
        json={"title": "Write the evaluation summary", "status": "proposed"},
        headers={"Idempotency-Key": "task-key-1"},
    )
    repeated = await client.post(
        "/api/v1/tasks",
        json={"title": "Write the evaluation summary", "status": "proposed"},
        headers={"Idempotency-Key": "task-key-1"},
    )
    assert created.json()["id"] == repeated.json()["id"]
    assert repeated.json()["duplicate"] is True

    memory = await client.post("/api/v1/memories", json={"content": "I prefer Python for AI backend development."})
    memory_id = memory.json()["memory"]["id"]
    deleted = await client.delete(f"/api/v1/memories/{memory_id}")
    assert deleted.status_code == 200
    listing = await client.get("/api/v1/memories")
    assert listing.json()["items"] == []

    run = await client.post("/api/v1/evaluations/runs", json={"use_sample_corpus": True})
    assert run.status_code == 202
    assert await process_next_job("test-worker")
    fetched = await client.get(f"/api/v1/evaluations/runs/{run.json()['id']}")
    body = fetched.json()
    assert body["run"]["status"] == "completed"
    assert body["run"]["metrics"]["disclaimer"]
    assert body["run"]["metrics"]["failed_cases"] == 0
    assert body["run"]["metrics"]["retrieval_recall_at_5"] == 1
