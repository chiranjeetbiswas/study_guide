"""The files a study set was made from (up to MAX_FILES per set).

A study set (collection `notes`) keeps its source files in `files`, a list of:

    name     file name ("pasted text" for pasted notes), unique inside the set
    type     "pdf" | "txt" | "text"
    pages    PDFs: [{"number": 1, "text": "..."}, ...]. None for the other types
    text     txt and pasted notes: the text. None for PDFs (their text is the pages joined by newlines)
    chars    length of the file's text

Every file is cleaned and chunked on its own (chunk_store.py): repeated headers and footers are found per file and
page numbers start at 1 in each file. The AI features that read the whole notes (revision notes, quiz, papers,
flashcards) get `notes.text`, the files joined with a "[Source: name]" line before each file. A set with one file has
no such line, so its text is exactly what it was before sets could have several files.

Sets made before this existed have no `files`: `files_of` builds the same list from their old single-file fields.
"""

import re

MAX_FILES = 3


def make_file(name: str, type_: str, *, text: str | None = None, pages: list[str] | None = None) -> dict:
    """A file record from what extract.py returns: `pages` for a PDF, `text` for anything else."""
    if pages is not None:
        record = {"name": name, "type": type_, "pages": [{"number": n, "text": t} for n, t in enumerate(pages, 1)], "text": None}
    else:
        record = {"name": name, "type": type_, "pages": None, "text": text or ""}
    record["chars"] = len(file_text(record))
    return record


def file_text(f: dict) -> str:
    if f.get("pages"):
        return "\n".join(p["text"] for p in f["pages"])
    return f.get("text") or ""


def combined_text(files: list[dict]) -> str:
    """One text for the AI features that read the whole notes."""
    if len(files) == 1:
        return file_text(files[0]).strip()
    return "\n\n".join(f"[Source: {f['name']}]\n{file_text(f).strip()}" for f in files)


def files_of(doc: dict) -> list[dict]:
    """The files of a study set, including sets made before `files` existed."""
    if doc.get("files"):
        return doc["files"]
    pages = doc.get("source_pages")
    legacy = {
        "name": doc.get("source_name") or "pasted text",
        "type": doc.get("source_type") or "text",
        "pages": pages or None,
        "text": None if pages else doc["text"],
    }
    legacy["chars"] = len(file_text(legacy))
    return [legacy]


def unique_names(names: list[str]) -> list[str]:
    """File names made distinct, so a source can always be told apart: a.pdf, a (2).pdf, a (3).pdf."""
    seen: dict[str, int] = {}
    out = []
    for name in names:
        key = name.lower()
        seen[key] = seen.get(key, 0) + 1
        if seen[key] == 1:
            out.append(name)
        else:
            stem, dot, ext = name.rpartition(".")
            out.append(f"{stem} ({seen[key]}).{ext}" if dot else f"{name} ({seen[key]})")
    return out


def default_title(files: list[dict]) -> str:
    """A title from the file names, for sets with several files and no subject."""
    stems = [re.sub(r"\.[A-Za-z0-9]{1,5}$", "", f["name"]) for f in files]
    return ", ".join(stems)[:100]
