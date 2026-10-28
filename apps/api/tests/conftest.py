import os
import tempfile

os.environ["ENVIRONMENT"] = "test"
os.environ["WORKER_MODE"] = "external"
os.environ["EMBEDDING_PROVIDER"] = "hashing"
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["EXPOSE_DEV_TOKENS"] = "true"
os.environ["REQUIRE_VERIFIED_EMAIL"] = "false"
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["DATABASE_URL"] = "postgresql+asyncpg://contextai:contextai@localhost:5434/contextai_test"
os.environ["STORAGE_PATH"] = tempfile.mkdtemp(prefix="contextai-test-")
os.environ["GOOGLE_API_KEY"] = ""

import asyncio

import pytest

pytest_plugins: list[str] = []


@pytest.fixture(scope="session")
def database_ready():
    async def prepare() -> None:
        import asyncpg

        connection = await asyncpg.connect("postgresql://contextai:contextai@localhost:5434/contextai")
        try:
            exists = await connection.fetchval("SELECT 1 FROM pg_database WHERE datname = 'contextai_test'")
            if not exists:
                await connection.execute("CREATE DATABASE contextai_test")
        finally:
            await connection.close()

    try:
        asyncio.run(prepare())
        from alembic import command
        from alembic.config import Config

        command.upgrade(Config("alembic.ini"), "head")
    except Exception as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")


@pytest.fixture
async def client(database_ready):
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text

    from app.db.session import SessionLocal
    from app.main import app

    async with SessionLocal() as session:
        await session.execute(
            text(
                """
                TRUNCATE TABLE
                    evaluation_results, evaluation_runs, evaluation_cases, evaluation_datasets,
                    tool_operations, tasks, memory_embeddings, memories,
                    document_embeddings, document_chunks, jobs, documents,
                    messages, conversations, audit_events, auth_tokens, sessions, users
                RESTART IDENTITY CASCADE
                """
            )
        )
        await session.commit()
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://test") as test_client:
            test_client.headers["X-Requested-With"] = "contextai"
            yield test_client
