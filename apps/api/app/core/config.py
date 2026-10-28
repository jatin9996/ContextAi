from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.constants import EMBEDDING_DIM


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "docker-compose.yml").exists() and (parent / "apps").exists():
            return parent
    return here.parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(repo_root() / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "ContextAI"
    environment: str = "development"
    secret_key: str = "change-me"
    database_url: str = "postgresql+asyncpg://contextai:contextai@localhost:5434/contextai"
    cors_origins: str = "http://localhost:3000"
    cookie_name: str = "contextai_session"
    cookie_secure: bool = False
    cookie_samesite: str = "lax"
    trust_proxy: bool = False
    session_ttl_hours: int = 336
    password_reset_ttl_minutes: int = 60
    email_verify_ttl_hours: int = 24
    max_sessions_per_user: int = 10
    expose_dev_tokens: bool = False
    require_verified_email: bool = False
    rate_limit_enabled: bool = True

    worker_mode: str | None = None
    worker_poll_seconds: float = 1.0
    stuck_job_minutes: int = 15
    stuck_stream_minutes: int = 10

    storage_backend: str = "local"
    storage_path: str | None = None
    s3_endpoint_url: str | None = None
    s3_bucket: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_region: str = "us-east-1"

    embedding_provider: str = "fastembed"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dimensions: int = EMBEDDING_DIM

    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "jatinjadequest@gmail.com"
    web_base_url: str = "http://localhost:3002"

    google_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    llm_timeout_seconds: int = 60
    gemini_input_cost_per_million: float = 0.15
    gemini_output_cost_per_million: float = 0.60

    max_upload_bytes: int = 20 * 1024 * 1024
    chunk_size: int = 700
    chunk_overlap: int = 100
    max_chunks: int = 400
    retrieval_candidates: int = 20
    retrieval_top_k: int = 5
    context_char_budget: int = 8000
    message_max_chars: int = 8000

    @field_validator("cookie_samesite")
    @classmethod
    def samesite(cls, value: str) -> str:
        allowed = {"lax", "strict", "none"}
        lowered = value.lower()
        if lowered not in allowed:
            raise ValueError("COOKIE_SAMESITE must be lax, strict, or none")
        return lowered

    @field_validator("embedding_provider")
    @classmethod
    def embedding_choice(cls, value: str) -> str:
        lowered = value.lower()
        if lowered not in {"fastembed", "hashing"}:
            raise ValueError("EMBEDDING_PROVIDER must be fastembed or hashing")
        return lowered

    @field_validator("storage_backend")
    @classmethod
    def storage_choice(cls, value: str) -> str:
        lowered = value.lower()
        if lowered not in {"local", "s3"}:
            raise ValueError("STORAGE_BACKEND must be local or s3")
        return lowered

    @model_validator(mode="after")
    def check_runtime(self) -> "Settings":
        if self.embedding_dimensions != EMBEDDING_DIM:
            raise ValueError(f"EMBEDDING_DIMENSIONS must stay {EMBEDDING_DIM} until the vector column is migrated")
        if self.cookie_samesite == "none" and not self.cookie_secure and self.environment == "production":
            raise ValueError("COOKIE_SECURE must be true when COOKIE_SAMESITE is none in production")
        if self.storage_backend == "s3" and not (self.s3_bucket and self.s3_access_key and self.s3_secret_key):
            raise ValueError("S3 storage requires S3_BUCKET, S3_ACCESS_KEY, and S3_SECRET_KEY")
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk overlap must be smaller than chunk size")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def resolved_storage_path(self) -> Path:
        if self.storage_path:
            return Path(self.storage_path).expanduser().resolve()
        return repo_root() / "data" / "storage"

    @property
    def resolved_worker_mode(self) -> str:
        if self.worker_mode:
            return self.worker_mode.lower()
        if self.environment == "development":
            return "embedded"
        return "external"

    @property
    def llm_configured(self) -> bool:
        return bool(self.google_api_key and self.google_api_key.strip())

    @property
    def mail_configured(self) -> bool:
        return bool(
            self.smtp_host.strip()
            and self.smtp_username
            and self.smtp_username.strip()
            and self.smtp_password
            and self.smtp_password.strip()
            and self.smtp_from.strip()
        )

    @property
    def sample_document_path(self) -> Path:
        return repo_root() / "samples" / "project-brief.md"


settings = Settings()
