EMBEDDING_DIM = 384

DOCUMENT_STATUSES = ("uploaded", "queued", "processing", "completed", "failed", "cancelled")
DOCUMENT_TRANSITIONS: dict[str, set[str]] = {
    "uploaded": {"queued", "cancelled"},
    "queued": {"processing", "cancelled"},
    "processing": {"completed", "failed", "cancelled", "queued"},
    "failed": {"queued"},
    "cancelled": {"queued"},
    "completed": {"queued"},
}

MEMORY_SOURCES = ("user", "document", "model_suggestion")
ACTIVE_MEMORY_STATUS = "active"
LANGUAGES = ("en", "es", "fr", "de", "hi")
RESPONSE_STYLES = ("concise", "balanced", "detailed")

ABSTENTION_MARKERS = (
    "do not establish",
    "does not establish",
    "don't establish",
    "insufficient evidence",
    "not enough evidence",
    "cannot find support",
)

SAMPLE_DATASET_NAME = "contextai-sample-v1"

AUDIT_METADATA_KEYS = {
    "filename",
    "label",
    "title",
    "status",
    "tool_name",
    "error_code",
    "count",
    "email_sha256",
}
