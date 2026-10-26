"""Stores the chunks of a document in MongoDB (RAG Phase 1b).

    notes (the document / study set)   <-- document_id --   chunks   <-- chunk_id --   (embeddings, Phase 2)

Collection `chunks`, one document per chunk:
    _id             the chunk id (later phases attach an embedding to exactly this id)
    document_id     _id of the notes document (study set) the chunk belongs to
    user_id         owner, copied from the document so ownership checks need no join
    chunk_index     0, 1, 2, ... in reading order
    content         text to embed: [overlap][blank line][new text]
    chars           len(content)
    overlap_chars   how many characters at the start of `content` repeat the previous chunk (0 = none)
    page_number     first PDF page of the new text, null when the source has no pages
    page_end        last page when the chunk spans pages, otherwise null
    heading         nearest heading above (or at) the start of the new text, null if none was detected
    section         the top-level heading it sits under, null if none was detected
    headings        headings that appear inside the new text
    source          file name the chunk came from ("pasted text" for pasted notes). A set can have up to 3 files
    source_type     "pdf" | "txt" | "text"
    end_kind        how the new text ends: "block" | "sentence" | "word"
    chunker_version, chunk_size, chunk_overlap, created_at   how and when it was made

The notes document records the settings of the current build in notes.chunking, so you can always tell
which experiment the stored chunks came from. Rebuilding replaces the old chunks of that document.

Phase 2 adds `embedding` and `embedding_model` to each chunk (see embeddings.py). They are filled in right after
the chunks are saved. If embedding fails, the chunks stay and notes.chunking.embedded_count is 0: call
POST /sets/{id}/chunks/embed to try again.
"""

import logging

from pymongo.database import Database

from app import models
from app.chunking import CHUNK_OVERLAP, CHUNK_SIZE, CHUNKER_VERSION, Page, chunk_document, pages_from_text
from app.documents import files_of
from app.embeddings import embed_document_chunks

log = logging.getLogger("chunk_store")


def _pages_of(f: dict) -> list[Page]:
    if f.get("pages"):
        return [Page(p["number"], p["text"]) for p in f["pages"]]
    return pages_from_text(f.get("text") or "")


def chunk_files(files: list[dict], size: int, overlap: int) -> tuple[list[dict], list[dict], int, int | None]:
    """Cleans and chunks every file on its own. Returns (chunks, per-file summary, noise lines removed, pdf pages).

    A file is chunked alone, so its repeated page headers and footers are found among its own pages only, page
    numbers start at 1 in each file, and no chunk ever mixes text from two files. Chunk numbers run on across the
    files in upload order (0, 1, 2, ...), because a set's chunk numbers must be unique. Raises ValueError for bad
    size or overlap settings.
    """
    chunks: list[dict] = []
    per_file: list[dict] = []
    noise = 0
    pdf_pages: int | None = None
    for f in files:
        result = chunk_document(_pages_of(f), size=size, overlap=overlap)
        start = len(chunks)
        for c in result.chunks:
            chunks.append(
                {
                    "chunk_index": start + c.index,
                    "content": c.content,
                    "chars": len(c.content),
                    "overlap_chars": c.overlap_chars,
                    "page_number": c.page_number,
                    "page_end": c.page_end,
                    "heading": c.heading,
                    "section": c.section,
                    "headings": c.headings,
                    "source": f["name"],
                    "source_type": f["type"],
                    "end_kind": c.end_kind,
                }
            )
        noise += sum(n["times"] for n in result.noise_removed)
        if f.get("pages"):
            pdf_pages = (pdf_pages or 0) + result.pages
        per_file.append({"name": f["name"], "type": f["type"], "chunks": len(chunks) - start, "pages": result.pages if f.get("pages") else None})
    return chunks, per_file, noise, pdf_pages


def build_and_store(db: Database, doc: dict, *, size: int | None = None, overlap: int | None = None) -> dict:
    """(Re)builds the chunks of a notes document (all of its files) and saves them. Returns the chunking summary."""
    size = CHUNK_SIZE if size is None else size
    overlap = CHUNK_OVERLAP if overlap is None else overlap
    chunks, per_file, noise, pages = chunk_files(files_of(doc), size, overlap)  # ValueError on bad settings

    created = models.now()
    rows = [
        {
            "document_id": doc["_id"],
            "user_id": doc["user_id"],
            **c,
            "chunker_version": CHUNKER_VERSION,
            "chunk_size": size,
            "chunk_overlap": overlap,
            "created_at": created,
        }
        for c in chunks
    ]
    db.chunks.delete_many({"document_id": doc["_id"]})
    if rows:
        db.chunks.insert_many(rows)

    info = {
        "chunker_version": CHUNKER_VERSION,
        "chunk_size": size,
        "chunk_overlap": overlap,
        "chunk_count": len(rows),
        "pages": pages,
        "noise_lines_removed": noise,
        "files": per_file,
        "built_at": created,
    }
    info.update(embed_quietly(db, doc["_id"]))
    db.notes.update_one({"_id": doc["_id"]}, {"$set": {"chunking": info}})
    return info


def embed_quietly(db: Database, document_id) -> dict:
    """Embeds a document's chunks. A failure (model not downloaded, out of memory) must not lose the chunks."""
    try:
        return embed_document_chunks(db, document_id)
    except Exception:
        log.exception("could not embed chunks of document %s", document_id)
        return {"embedding_model": None, "embedding_dim": None, "embedded_count": 0}


def build_quietly(db: Database, doc: dict) -> None:
    """Chunking must never stop a study set from being created: on failure, log it. It can be rebuilt later."""
    try:
        build_and_store(db, doc)
    except Exception:
        log.exception("could not chunk document %s", doc.get("_id"))
