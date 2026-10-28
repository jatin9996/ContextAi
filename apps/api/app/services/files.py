from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePath
import zipfile

from app.core.errors import AppError

ALLOWED_EXTENSIONS = {"pdf", "txt", "md", "docx"}
MIME_TYPES = {
    "pdf": "application/pdf",
    "txt": "text/plain",
    "md": "text/markdown",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
EXECUTABLE_SIGNATURES = (
    b"MZ",
    b"\x7fELF",
    b"\xfe\xed\xfa\xce",
    b"\xfe\xed\xfa\xcf",
    b"#!",
)


@dataclass(frozen=True)
class ValidatedUpload:
    filename: str
    extension: str
    mime_type: str
    size_bytes: int
    data: bytes


def sanitize_filename(filename: str) -> str:
    name = PurePath(filename or "").name.strip().replace("\x00", "")
    if name in {"", ".", ".."}:
        raise AppError("invalid_file", "The file name is not valid.")
    cleaned = "".join(ch for ch in name if ch.isprintable() and ch not in "\\/")
    cleaned = cleaned.strip(" .")
    if not cleaned:
        raise AppError("invalid_file", "The file name is not valid.")
    return cleaned[:200]


def _looks_like_text(data: bytes) -> bool:
    if b"\x00" in data:
        return False
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    if not text.strip():
        return False
    controls = sum(1 for char in text if ord(char) < 32 and char not in "\n\r\t")
    return controls / max(len(text), 1) < 0.02


def _reject_executable(data: bytes) -> None:
    if data.startswith(EXECUTABLE_SIGNATURES):
        raise AppError("rejected_file", "Executable or script content is not allowed.")


def _validate_docx(data: bytes) -> None:
    if not data.startswith(b"PK\x03\x04"):
        raise AppError("invalid_file", "The DOCX file is not a valid Office document.")
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            names = set(archive.namelist())
            if "word/document.xml" not in names:
                raise AppError("invalid_file", "The DOCX file is missing its document content.")
            declared = sum(info.file_size for info in archive.infolist())
            if declared > 40 * 1024 * 1024:
                raise AppError("invalid_file", "The DOCX file expands beyond the allowed size.")
    except zipfile.BadZipFile as exc:
        raise AppError("invalid_file", "The DOCX file is malformed.") from exc


def validate_upload(filename: str, data: bytes, *, max_bytes: int) -> ValidatedUpload:
    safe_name = sanitize_filename(filename)
    extension = PurePath(safe_name).suffix.lower().lstrip(".")
    if extension not in ALLOWED_EXTENSIONS:
        raise AppError("unsupported_file", "Upload a PDF, TXT, Markdown, or DOCX file.")
    if not data:
        raise AppError("invalid_file", "The file is empty.")
    if len(data) > max_bytes:
        raise AppError("file_too_large", "The file is larger than 20 MB.")
    _reject_executable(data)
    if extension == "pdf":
        if not data.startswith(b"%PDF") or b"%%EOF" not in data[-2048:] and b"%%EOF" not in data:
            raise AppError("invalid_file", "The PDF file is malformed.")
    elif extension == "docx":
        _validate_docx(data)
    elif not _looks_like_text(data):
        raise AppError("invalid_file", "Text uploads must be valid UTF-8 documents.")
    return ValidatedUpload(
        filename=safe_name,
        extension=extension,
        mime_type=MIME_TYPES[extension],
        size_bytes=len(data),
        data=data,
    )
