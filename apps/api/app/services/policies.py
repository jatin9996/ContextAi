import re

from app.core.constants import ABSTENTION_MARKERS, DOCUMENT_TRANSITIONS
from app.core.errors import AppError
from app.services.textutil import CITE_RE, jaccard, tokenize


def assert_document_transition(current: str, new: str) -> None:
    allowed = DOCUMENT_TRANSITIONS.get(current, set())
    if new not in allowed:
        raise AppError("invalid_state", f"Cannot move a document from {current} to {new}.", 409)


def is_abstention(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in ABSTENTION_MARKERS)


def validate_citations(answer: str, sources: dict[str, dict]) -> tuple[str, list[dict]]:
    used: list[dict] = []
    seen: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        source = sources.get(key)
        if source is None:
            return ""
        if key not in seen:
            seen.add(key)
            used.append(source)
        return f"[{key}]"

    cleaned = CITE_RE.sub(replace, answer)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r" +([.,;:])", r"\1", cleaned)
    return cleaned.strip(), used


def memory_is_relevant(*, similarity: float, overlap: bool, embedding_provider: str) -> bool:
    """Lexical overlap is enough. Otherwise require a clearly related vector.

    bge-small scores unrelated personal facts around 0.45 and a real paraphrase near 0.85.
    """
    if overlap:
        return True
    if embedding_provider == "hashing":
        return False
    return similarity >= 0.62


def should_abstain_documents(query: str, chunks: list[dict], *, embedding_provider: str) -> bool:
    if not chunks:
        return True
    query_tokens = tokenize(query)
    overlap = any(query_tokens & tokenize(str(chunk.get("content", ""))) for chunk in chunks)
    if overlap:
        return False
    if embedding_provider == "hashing":
        return True
    top = float(chunks[0].get("semantic_similarity") or 0)
    return top < 0.55


def select_answer_mode(*, document_supported: bool, memory_supported: bool) -> str:
    if document_supported and memory_supported:
        return "mixed"
    if document_supported:
        return "documents"
    if memory_supported:
        return "memories"
    return "abstain"


def classify_memory_overlap(token_jaccard: float, semantic: float | None) -> str:
    if token_jaccard >= 0.85:
        return "duplicate"
    if token_jaccard >= 0.45 or (semantic is not None and semantic >= 0.82):
        return "conflict"
    return "ok"


def memory_jaccard(left: str, right: str) -> float:
    return jaccard(tokenize(left), tokenize(right))


def forced_task_status(invoked_by: str, requested: str | None) -> str:
    if invoked_by == "model":
        return "proposed"
    if requested in {"proposed", "open"}:
        return requested
    return "proposed"


def forced_memory_status(*, source: str, invoked_by: str, requested: str | None) -> str:
    if source == "model_suggestion" or invoked_by == "model":
        return "suggested"
    if requested in {"active", "suggested", "conflict_pending"}:
        return requested
    return "active"


def guard_due_date(due_iso: str | None, source_text: str, excerpt: str | None) -> str | None:
    if not due_iso:
        return None
    haystack = f"{source_text}\n{excerpt or ''}"
    if due_iso not in haystack:
        return None
    return due_iso


def guard_due_label(label: str | None, source_text: str) -> str | None:
    if not label:
        return None
    if label.lower() not in source_text.lower():
        return None
    return label


def authorize_tool_call(*, consequential: bool, approved: bool) -> str | None:
    if consequential and not approved:
        return "approval_required"
    return None
