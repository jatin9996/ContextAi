import re
from dataclasses import dataclass

from app.services.textutil import normalize_text

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


@dataclass
class PageText:
    page: int | None
    text: str


@dataclass
class ChunkDraft:
    content: str
    page_start: int | None
    page_end: int | None
    section: str | None
    token_count: int


def _split_long(text: str, size: int, overlap: int) -> list[str]:
    if len(text) <= size:
        return [text]
    pieces: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        pieces.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [piece for piece in pieces if piece]


def _pack(paragraphs: list[str], size: int, overlap: int) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    expanded: list[str] = []
    for paragraph in paragraphs:
        expanded.extend(_split_long(paragraph, size, overlap))
    for paragraph in expanded:
        addition = len(paragraph) + (2 if current else 0)
        if current and current_len + addition > size:
            chunks.append("\n\n".join(current).strip())
            tail: list[str] = []
            tail_len = 0
            for piece in reversed(current):
                if tail and tail_len + len(piece) > overlap:
                    break
                tail.append(piece)
                tail_len += len(piece)
            current = list(reversed(tail))
            current_len = sum(len(piece) + 2 for piece in current)
        current.append(paragraph)
        current_len += len(paragraph) + 2
    if current:
        chunks.append("\n\n".join(current).strip())
    return [chunk for chunk in chunks if chunk]


def _sections(text: str) -> list[tuple[str | None, str]]:
    lines = text.splitlines()
    sections: list[tuple[str | None, list[str]]] = []
    current_title: str | None = None
    buffer: list[str] = []
    for line in lines:
        match = HEADING_RE.match(line.strip())
        if match:
            if buffer or current_title:
                sections.append((current_title, buffer))
            current_title = match.group(2).strip()[:200]
            buffer = []
            continue
        buffer.append(line)
    if buffer or current_title:
        sections.append((current_title, buffer))
    result: list[tuple[str | None, str]] = []
    for title, body_lines in sections:
        body = normalize_text("\n".join(body_lines))
        if title and body:
            result.append((title, f"{title}\n\n{body}"))
        elif title:
            result.append((title, title))
        elif body:
            result.append((None, body))
    return result


def chunk_pages(pages: list[PageText], *, chunk_size: int = 700, overlap: int = 100) -> list[ChunkDraft]:
    drafts: list[ChunkDraft] = []
    for page in pages:
        text = normalize_text(page.text)
        if not text:
            continue
        for section, body in _sections(text):
            for piece in _pack(re.split(r"\n\s*\n", body), chunk_size, overlap):
                content = piece.strip()
                if len(content) < 2:
                    continue
                drafts.append(
                    ChunkDraft(
                        content=content,
                        page_start=page.page,
                        page_end=page.page,
                        section=section,
                        token_count=max(1, len(content) // 4),
                    )
                )
    return drafts
