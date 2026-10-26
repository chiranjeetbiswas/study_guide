import io

from pypdf import PdfReader

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_PDF_PAGES = 100


class ExtractError(Exception):
    """A problem with the uploaded file that the user can act on. The message is safe to show."""


def extract_text(filename: str, data: bytes) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        return _from_pdf(data)
    if name.endswith(".txt"):
        return _from_txt(data)
    raise ExtractError("Only .pdf and .txt files are supported.")


def _from_txt(data: bytes) -> str:
    if b"\x00" in data:
        raise ExtractError("This doesn't look like a plain text file.")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Older Windows text files are often cp1252
        return data.decode("cp1252", errors="replace")


def extract_document(filename: str, data: bytes) -> tuple[str, list[str] | None]:
    """(text, pages). `text` is exactly what extract_text() returns. `pages` is the text of each PDF page in
    order (page 1 first), or None for formats that have no pages. Keeping the pages is what lets the chunker
    record which page a piece of text came from."""
    if filename.lower().endswith(".pdf"):
        pages = _pdf_pages(data)
        return "\n".join(pages), pages
    return extract_text(filename, data), None


def _from_pdf(data: bytes) -> str:
    return "\n".join(_pdf_pages(data))


def _pdf_pages(data: bytes) -> list[str]:
    # Check the content, not just the extension
    if not data.startswith(b"%PDF-"):
        raise ExtractError("This file isn't a valid PDF.")
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ExtractError("Password-protected PDFs aren't supported.")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise ExtractError(f"This PDF has more than {MAX_PDF_PAGES} pages. Upload a shorter section.")
        pages = [(page.extract_text() or "") for page in reader.pages]
    except ExtractError:
        raise
    except Exception:
        raise ExtractError("Couldn't read this PDF. It may be damaged.")

    if not "\n".join(pages).strip():
        raise ExtractError("No selectable text found. Scanned PDFs are images and need OCR, which isn't supported.")
    return pages
