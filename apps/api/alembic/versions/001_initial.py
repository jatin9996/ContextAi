"""Initial ContextAI schema.

Revision ID: 001_initial
Revises:
Create Date: 2026-10-28
"""

from alembic import op

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None

# Embedding width is fixed at 384 for BAAI/bge-small-en-v1.5.
# Changing it requires a new migration. Keep app.core.constants.EMBEDDING_DIM in sync.

STATEMENTS = [
    "CREATE EXTENSION IF NOT EXISTS vector",
    "CREATE EXTENSION IF NOT EXISTS citext",
    """
    CREATE TABLE users (
        id UUID PRIMARY KEY,
        email CITEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        display_name VARCHAR(80) NOT NULL,
        timezone VARCHAR(64) NOT NULL DEFAULT 'UTC',
        preferred_language VARCHAR(8) NOT NULL DEFAULT 'en',
        response_style VARCHAR(16) NOT NULL DEFAULT 'balanced',
        memory_enabled BOOLEAN NOT NULL DEFAULT TRUE,
        email_verified_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT users_response_style_chk CHECK (response_style IN ('concise', 'balanced', 'detailed')),
        CONSTRAINT users_language_chk CHECK (preferred_language IN ('en', 'es', 'fr', 'de', 'hi'))
    )
    """,
    """
    CREATE TABLE sessions (
        id UUID PRIMARY KEY,
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        token_hash CHAR(64) NOT NULL UNIQUE,
        expires_at TIMESTAMPTZ NOT NULL,
        revoked_at TIMESTAMPTZ,
        user_agent VARCHAR(300),
        ip_address VARCHAR(64),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX sessions_user_id_idx ON sessions (user_id, created_at DESC)",
    """
    CREATE TABLE auth_tokens (
        id UUID PRIMARY KEY,
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        purpose VARCHAR(32) NOT NULL,
        token_hash CHAR(64) NOT NULL UNIQUE,
        expires_at TIMESTAMPTZ NOT NULL,
        used_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT auth_tokens_purpose_chk CHECK (purpose IN ('email_verify', 'password_reset'))
    )
    """,
    "CREATE INDEX auth_tokens_user_idx ON auth_tokens (user_id, purpose)",
    """
    CREATE TABLE conversations (
        id UUID PRIMARY KEY,
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        title VARCHAR(160) NOT NULL DEFAULT 'New conversation',
        archived_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX conversations_user_idx ON conversations (user_id, updated_at DESC)",
    """
    CREATE TABLE messages (
        id UUID PRIMARY KEY,
        conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        role VARCHAR(16) NOT NULL,
        content TEXT NOT NULL DEFAULT '',
        status VARCHAR(16) NOT NULL DEFAULT 'completed',
        citations JSONB NOT NULL DEFAULT '[]'::jsonb,
        evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
        diagnostics JSONB NOT NULL DEFAULT '{}'::jsonb,
        usage JSONB NOT NULL DEFAULT '{}'::jsonb,
        actions JSONB NOT NULL DEFAULT '[]'::jsonb,
        idempotency_key VARCHAR(80),
        error_code VARCHAR(64),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT messages_role_chk CHECK (role IN ('user', 'assistant', 'tool')),
        CONSTRAINT messages_status_chk CHECK (status IN ('streaming', 'completed', 'failed', 'incomplete'))
    )
    """,
    "CREATE INDEX messages_conversation_idx ON messages (conversation_id, created_at, id)",
    """
    CREATE UNIQUE INDEX messages_idempotency_idx
    ON messages (conversation_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL
    """,
    """
    CREATE TABLE documents (
        id UUID PRIMARY KEY,
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        filename VARCHAR(200) NOT NULL,
        label VARCHAR(200) NOT NULL,
        mime_type VARCHAR(160) NOT NULL,
        extension VARCHAR(10) NOT NULL,
        size_bytes INTEGER NOT NULL,
        storage_key TEXT NOT NULL,
        content_sha256 CHAR(64) NOT NULL,
        status VARCHAR(20) NOT NULL,
        error_code VARCHAR(64),
        error_message TEXT,
        page_count INTEGER,
        chunk_count INTEGER NOT NULL DEFAULT 0,
        cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT documents_status_chk CHECK (
            status IN ('uploaded', 'queued', 'processing', 'completed', 'failed', 'cancelled')
        ),
        CONSTRAINT documents_size_chk CHECK (size_bytes >= 0)
    )
    """,
    "CREATE INDEX documents_user_idx ON documents (user_id, created_at DESC)",
    "CREATE INDEX documents_user_checksum_idx ON documents (user_id, content_sha256)",
    """
    CREATE TABLE document_chunks (
        id UUID PRIMARY KEY,
        document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        chunk_index INTEGER NOT NULL,
        content TEXT NOT NULL,
        page_start INTEGER,
        page_end INTEGER,
        section VARCHAR(200),
        token_count INTEGER NOT NULL DEFAULT 0,
        content_tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT document_chunks_unique_index UNIQUE (document_id, chunk_index),
        CONSTRAINT document_chunks_content_chk CHECK (length(content) > 0)
    )
    """,
    "CREATE INDEX document_chunks_user_idx ON document_chunks (user_id)",
    "CREATE INDEX document_chunks_tsv_idx ON document_chunks USING GIN (content_tsv)",
    """
    CREATE TABLE document_embeddings (
        chunk_id UUID PRIMARY KEY REFERENCES document_chunks(id) ON DELETE CASCADE,
        document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        embedding vector(384) NOT NULL
    )
    """,
    "CREATE INDEX document_embeddings_user_idx ON document_embeddings (user_id)",
    """
    CREATE INDEX document_embeddings_hnsw
    ON document_embeddings USING hnsw (embedding vector_cosine_ops)
    """,
    """
    CREATE TABLE memories (
        id UUID PRIMARY KEY,
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        content TEXT NOT NULL,
        source VARCHAR(32) NOT NULL,
        status VARCHAR(32) NOT NULL,
        conflict_with_id UUID REFERENCES memories(id) ON DELETE SET NULL,
        version INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT memories_source_chk CHECK (source IN ('user', 'document', 'model_suggestion')),
        CONSTRAINT memories_status_chk CHECK (
            status IN ('active', 'suggested', 'conflict_pending', 'rejected', 'superseded')
        )
    )
    """,
    "CREATE INDEX memories_user_idx ON memories (user_id, updated_at DESC)",
    """
    CREATE TABLE memory_embeddings (
        memory_id UUID PRIMARY KEY REFERENCES memories(id) ON DELETE CASCADE,
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        embedding vector(384) NOT NULL
    )
    """,
    """
    CREATE INDEX memory_embeddings_hnsw
    ON memory_embeddings USING hnsw (embedding vector_cosine_ops)
    """,
    """
    CREATE TABLE tasks (
        id UUID PRIMARY KEY,
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        title VARCHAR(200) NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        due_date DATE,
        due_label VARCHAR(80),
        priority VARCHAR(16),
        status VARCHAR(16) NOT NULL,
        source_type VARCHAR(32),
        source_id UUID,
        source_excerpt TEXT,
        confidence REAL,
        idempotency_key VARCHAR(120),
        normalized_title VARCHAR(200) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT tasks_status_chk CHECK (status IN ('proposed', 'open', 'completed', 'cancelled')),
        CONSTRAINT tasks_priority_chk CHECK (priority IS NULL OR priority IN ('low', 'medium', 'high'))
    )
    """,
    "CREATE INDEX tasks_user_status_idx ON tasks (user_id, status, updated_at DESC)",
    """
    CREATE UNIQUE INDEX tasks_idempotency_idx
    ON tasks (user_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL
    """,
    """
    CREATE TABLE tool_operations (
        id UUID PRIMARY KEY,
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        tool_name VARCHAR(64) NOT NULL,
        idempotency_key VARCHAR(160),
        status VARCHAR(32) NOT NULL,
        resource_type VARCHAR(32),
        resource_id UUID,
        error_category VARCHAR(64),
        arguments JSONB NOT NULL DEFAULT '{}'::jsonb,
        result JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT tool_operations_status_chk CHECK (
            status IN ('succeeded', 'failed', 'rejected', 'pending_approval')
        )
    )
    """,
    "CREATE INDEX tool_operations_user_idx ON tool_operations (user_id, created_at DESC)",
    """
    CREATE UNIQUE INDEX tool_operations_idempotency_idx
    ON tool_operations (user_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL
    """,
    """
    CREATE TABLE evaluation_datasets (
        id UUID PRIMARY KEY,
        name VARCHAR(120) NOT NULL UNIQUE,
        description TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE evaluation_cases (
        id UUID PRIMARY KEY,
        dataset_id UUID NOT NULL REFERENCES evaluation_datasets(id) ON DELETE CASCADE,
        case_type VARCHAR(32) NOT NULL,
        question TEXT,
        expected_substrings JSONB NOT NULL DEFAULT '[]'::jsonb,
        expect_abstention BOOLEAN NOT NULL DEFAULT FALSE,
        tool_name VARCHAR(64),
        tool_arguments JSONB NOT NULL DEFAULT '{}'::jsonb,
        expected JSONB NOT NULL DEFAULT '{}'::jsonb,
        sort_order INTEGER NOT NULL DEFAULT 0,
        CONSTRAINT evaluation_cases_type_chk CHECK (case_type IN ('retrieval', 'answer', 'workflow'))
    )
    """,
    "CREATE INDEX evaluation_cases_dataset_idx ON evaluation_cases (dataset_id, sort_order)",
    """
    CREATE TABLE evaluation_runs (
        id UUID PRIMARY KEY,
        dataset_id UUID NOT NULL REFERENCES evaluation_datasets(id) ON DELETE RESTRICT,
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        status VARCHAR(16) NOT NULL,
        config JSONB NOT NULL DEFAULT '{}'::jsonb,
        metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
        error_code VARCHAR(64),
        started_at TIMESTAMPTZ,
        finished_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT evaluation_runs_status_chk CHECK (status IN ('queued', 'running', 'completed', 'failed'))
    )
    """,
    "CREATE INDEX evaluation_runs_user_idx ON evaluation_runs (user_id, created_at DESC)",
    """
    CREATE TABLE evaluation_results (
        id UUID PRIMARY KEY,
        run_id UUID NOT NULL REFERENCES evaluation_runs(id) ON DELETE CASCADE,
        case_id UUID NOT NULL REFERENCES evaluation_cases(id) ON DELETE CASCADE,
        passed BOOLEAN NOT NULL,
        failure_reason TEXT,
        metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
        details JSONB NOT NULL DEFAULT '{}'::jsonb,
        CONSTRAINT evaluation_results_unique UNIQUE (run_id, case_id)
    )
    """,
    """
    CREATE TABLE audit_events (
        id UUID PRIMARY KEY,
        user_id UUID REFERENCES users(id) ON DELETE SET NULL,
        action VARCHAR(64) NOT NULL,
        resource_type VARCHAR(32),
        resource_id UUID,
        trace_id VARCHAR(64),
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX audit_events_user_idx ON audit_events (user_id, created_at DESC)",
    """
    CREATE TABLE jobs (
        id UUID PRIMARY KEY,
        job_type VARCHAR(64) NOT NULL,
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        status VARCHAR(16) NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        max_attempts INTEGER NOT NULL DEFAULT 3,
        run_after TIMESTAMPTZ NOT NULL DEFAULT now(),
        locked_at TIMESTAMPTZ,
        locked_by VARCHAR(80),
        last_error TEXT,
        document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT jobs_status_chk CHECK (
            status IN ('queued', 'running', 'succeeded', 'dead', 'cancelled')
        ),
        CONSTRAINT jobs_attempts_chk CHECK (attempts >= 0)
    )
    """,
    "CREATE INDEX jobs_claim_idx ON jobs (status, run_after, created_at)",
    """
    CREATE UNIQUE INDEX jobs_one_active_document_idx
    ON jobs (document_id)
    WHERE status IN ('queued', 'running') AND document_id IS NOT NULL
    """,
]

DOWNGRADE = [
    "DROP TABLE IF EXISTS jobs CASCADE",
    "DROP TABLE IF EXISTS audit_events CASCADE",
    "DROP TABLE IF EXISTS evaluation_results CASCADE",
    "DROP TABLE IF EXISTS evaluation_runs CASCADE",
    "DROP TABLE IF EXISTS evaluation_cases CASCADE",
    "DROP TABLE IF EXISTS evaluation_datasets CASCADE",
    "DROP TABLE IF EXISTS tool_operations CASCADE",
    "DROP TABLE IF EXISTS tasks CASCADE",
    "DROP TABLE IF EXISTS memory_embeddings CASCADE",
    "DROP TABLE IF EXISTS memories CASCADE",
    "DROP TABLE IF EXISTS document_embeddings CASCADE",
    "DROP TABLE IF EXISTS document_chunks CASCADE",
    "DROP TABLE IF EXISTS documents CASCADE",
    "DROP TABLE IF EXISTS messages CASCADE",
    "DROP TABLE IF EXISTS conversations CASCADE",
    "DROP TABLE IF EXISTS auth_tokens CASCADE",
    "DROP TABLE IF EXISTS sessions CASCADE",
    "DROP TABLE IF EXISTS users CASCADE",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(statement)
