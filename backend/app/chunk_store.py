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
    source          file name the document came from ("pasted text" for pasted notes, null for old sets)
    source_type     "pdf" | "txt" | "text" | null
    end_kind        how the new text ends: "block" | "sentence" | "word"
    chunker_version, chunk_size, chunk_overlap, created_at   how and when it was made

The notes document records the settings of the current build in notes.chunking, so you can always tell
which experiment the stored chunks came from. Rebuilding replaces the old chunks of that document.
"""

import logging

from pymongo.database import Database

from app import models
from app.chunking import CHUNK_OVERLAP, CHUNK_SIZE, CHUNKER_VERSION, Page, chunk_document, pages_from_text

log = logging.getLogger("chunk_store")


def _pages_of(doc: dict) -> list[Page]:
    stored = doc.get("source_pages")
    if stored:
        return [Page(p["number"], p["text"]) for p in stored]
    return pages_from_text(doc["text"])


def build_and_store(db: Database, doc: dict, *, size: int | None = None, overlap: int | None = None) -> dict:
    """(Re)builds the chunks of a notes document and saves them. Returns the chunking summary."""
    size = CHUNK_SIZE if size is None else size
    overlap = CHUNK_OVERLAP if overlap is None else overlap
    result = chunk_document(_pages_of(doc), size=size, overlap=overlap)  # raises ValueError on bad settings

    created = models.now()
    source, source_type = doc.get("source_name"), doc.get("source_type")
    rows = [
        {
            "document_id": doc["_id"],
            "user_id": doc["user_id"],
            "chunk_index": c.index,
            "content": c.content,
            "chars": len(c.content),
            "overlap_chars": c.overlap_chars,
            "page_number": c.page_number,
            "page_end": c.page_end,
            "heading": c.heading,
            "section": c.section,
            "headings": c.headings,
            "source": source,
            "source_type": source_type,
            "end_kind": c.end_kind,
            "chunker_version": CHUNKER_VERSION,
            "chunk_size": size,
            "chunk_overlap": overlap,
            "created_at": created,
        }
        for c in result.chunks
    ]
    db.chunks.delete_many({"document_id": doc["_id"]})
    if rows:
        db.chunks.insert_many(rows)

    info = {
        "chunker_version": CHUNKER_VERSION,
        "chunk_size": size,
        "chunk_overlap": overlap,
        "chunk_count": len(rows),
        "pages": result.pages if doc.get("source_pages") else None,
        "noise_lines_removed": sum(n["times"] for n in result.noise_removed),
        "built_at": created,
    }
    db.notes.update_one({"_id": doc["_id"]}, {"$set": {"chunking": info}})
    return info


def build_quietly(db: Database, doc: dict) -> None:
    """Chunking must never stop a study set from being created: on failure, log it. It can be rebuilt later."""
    try:
        build_and_store(db, doc)
    except Exception:
        log.exception("could not chunk document %s", doc.get("_id"))
