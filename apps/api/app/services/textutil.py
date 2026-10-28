import re

STOPWORDS = {
    "the",
    "a",
    "an",
    "is",
    "are",
    "was",
    "were",
    "what",
    "how",
    "why",
    "when",
    "where",
    "who",
    "of",
    "to",
    "and",
    "or",
    "for",
    "in",
    "on",
    "my",
    "me",
    "do",
    "does",
    "did",
    "with",
    "about",
    "please",
    "this",
    "that",
    "from",
    "into",
    "your",
    "you",
}

TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{2,}")
IDENT_RE = re.compile(r"\b(?:[A-Z]{2,}(?:-[A-Z0-9]+)+|[A-Za-z0-9_-]*\d[A-Za-z0-9_-]{2,})\b")
CITE_RE = re.compile(r"\[([SM]\d+)\]")
FOLLOW_RE = re.compile(r"^(what about|how about|and the|also|tell me more|expand on)\b", re.IGNORECASE)


def normalize_text(value: str) -> str:
    value = value.replace("\x00", "")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def tokenize(value: str) -> set[str]:
    return {match.group(0).lower() for match in TOKEN_RE.finditer(value) if match.group(0).lower() not in STOPWORDS}


def identifiers(value: str) -> list[str]:
    found: list[str] = []
    for match in IDENT_RE.finditer(value):
        token = match.group(0)
        if 3 <= len(token) <= 64 and token not in found:
            found.append(token)
        if len(found) == 5:
            break
    return found


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def containment(part: set[str], whole: set[str]) -> float:
    if not part:
        return 0.0
    return len(part & whole) / len(part)


def trim_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    if max_chars < 2:
        return value[:max_chars]
    return value[: max_chars - 1].rstrip() + "…"


def excerpt_around(text: str, query: str, size: int = 360) -> str:
    tokens = [token for token in identifiers(query)] or list(tokenize(query))
    lowered = text.lower()
    index = -1
    for token in tokens:
        index = lowered.find(token.lower())
        if index >= 0:
            break
    if index < 0:
        return trim_text(text, size)
    start = max(0, index - size // 3)
    end = min(len(text), start + size)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet


def fence(value: str) -> str:
    return value.replace("</evidence>", "</ evidence>").replace("</memory>", "</ memory>")


def title_from_message(content: str) -> str:
    line = re.sub(r"\s+", " ", content.strip().splitlines()[0]).strip(" -")
    if not line:
        return "New conversation"
    if len(line) > 72:
        return line[:71].rstrip() + "…"
    return line


def build_search_query(latest: str, previous_user: str | None) -> str:
    text = latest.strip()
    if previous_user and FOLLOW_RE.match(text):
        return f"{previous_user.strip()}\n{text}"
    return text


def normalize_title(title: str) -> str:
    cleaned = title.lower()
    cleaned = re.sub(r"[^a-z0-9\s]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:200]


def l2_normalize(vector: list[float]) -> list[float]:
    norm = sum(value * value for value in vector) ** 0.5
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in vector) + "]"
