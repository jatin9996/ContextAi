from io import BytesIO

from app.core.errors import ProcessingError
from app.services.chunking import PageText
from app.services.textutil import normalize_text


def extract_document(extension: str, data: bytes) -> list[PageText]:
    if extension == "pdf":
        return _extract_pdf(data)
    if extension == "docx":
        return _extract_docx(data)
    if extension in {"txt", "md"}:
        return [PageText(page=None, text=normalize_text(data.decode("utf-8")))]
    raise ProcessingError("unsupported_type", "This file type is not supported.")


def _extract_pdf(data: bytes) -> list[PageText]:
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except Exception as exc:
        raise ProcessingError("dependency_missing", "PDF extraction is unavailable.") from exc
    try:
        reader = PdfReader(BytesIO(data))
    except Exception as exc:
        raise ProcessingError("unreadable_file", "The PDF could not be read.") from exc
    if reader.is_encrypted:
        raise ProcessingError("encrypted_file", "Encrypted files are not supported.")
    pages: list[PageText] = []
    try:
        for index, page in enumerate(reader.pages, start=1):
            pages.append(PageText(page=index, text=normalize_text(page.extract_text() or "")))
    except PdfReadError as exc:
        raise ProcessingError("unreadable_file", "The PDF could not be read.") from exc
    return pages


def _extract_docx(data: bytes) -> list[PageText]:
    try:
        from docx import Document
    except Exception as exc:
        raise ProcessingError("dependency_missing", "DOCX extraction is unavailable.") from exc
    try:
        document = Document(BytesIO(data))
    except Exception as exc:
        raise ProcessingError("unreadable_file", "The DOCX file could not be read.") from exc
    paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
    return [PageText(page=None, text=normalize_text("\n\n".join(paragraphs)))]
