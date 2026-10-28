from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterRequest(APIModel):
    email: EmailStr
    password: str
    display_name: str = Field(min_length=1, max_length=80)


class LoginRequest(APIModel):
    email: EmailStr
    password: str


class ForgotPasswordRequest(APIModel):
    email: EmailStr


class ResetPasswordRequest(APIModel):
    token: str = Field(min_length=10, max_length=200)
    password: str


class ChangePasswordRequest(APIModel):
    current_password: str
    new_password: str


class VerifyEmailRequest(APIModel):
    token: str = Field(min_length=10, max_length=200)


class ProfileUpdate(APIModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    preferred_language: str | None = None
    response_style: str | None = None
    memory_enabled: bool | None = None


class DeleteAccountRequest(APIModel):
    password: str
    confirmation: str

    @field_validator("confirmation")
    @classmethod
    def confirm(cls, value: str) -> str:
        if value != "DELETE":
            raise ValueError("Type DELETE to confirm account deletion.")
        return value


class ConversationCreate(APIModel):
    title: str | None = Field(default=None, max_length=160)


class ConversationUpdate(APIModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    archived: bool | None = None


class MessageCreate(APIModel):
    content: str = Field(min_length=1, max_length=8000)

    @field_validator("content")
    @classmethod
    def not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Message is empty.")
        if len(cleaned) > 8000:
            raise ValueError("Message is too long.")
        return cleaned


class DocumentUpdate(APIModel):
    label: str = Field(min_length=1, max_length=200)


class SearchRequest(APIModel):
    query: str = Field(min_length=1, max_length=500)
    document_id: UUID | None = None
    file_type: str | None = None
    uploaded_after: datetime | None = None
    limit: int = Field(default=8, ge=1, le=20)


class MemoryCreate(APIModel):
    content: str = Field(min_length=3, max_length=4000)
    confirm_conflicts: bool = False


class MemoryUpdate(APIModel):
    content: str | None = Field(default=None, min_length=3, max_length=4000)
    status: str | None = None


class MemoryResolve(APIModel):
    action: str


class TaskCreate(APIModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = ""
    due_date: str | None = None
    due_label: str | None = None
    priority: str | None = None
    status: str = "open"
    allow_duplicate: bool = False


class TaskUpdate(APIModel):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = None
    due_date: str | None = None
    due_label: str | None = None
    priority: str | None = None
    status: str | None = None


class TaskExtractRequest(APIModel):
    document_id: UUID | None = None
    conversation_id: UUID | None = None


class EvaluationRunCreate(APIModel):
    use_sample_corpus: bool = True
