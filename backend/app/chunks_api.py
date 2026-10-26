"""Read and rebuild the stored chunks of a study set (RAG Phase 1b).

  GET  /sets/{id}/chunks            the stored chunks and the settings they were built with
  POST /sets/{id}/chunks/rebuild    rebuild them, optionally with a different size / overlap (for experiments)

  POST /sets/{id}/chunks/embed      (re)compute the embeddings of the stored chunks (Phase 2)
  GET  /sets/{id}/chunks/search     the best chunks for a question: mode=hybrid (default), vector or keyword
                                    (to check the embeddings and compare the search methods)

Rebuilding only replaces this set's chunks. It does not touch flashcards, revision notes, quizzes or papers.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from pymongo.database import Database

from app.auth import get_current_user
from app.chunk_store import build_and_store, embed_quietly
from app.database import get_db
from app.retrieval import Mode, search as search_hits
from app.studyset import _get_set

router = APIRouter(prefix="/sets/{set_id}/chunks", tags=["chunks"])


class ChunkOut(BaseModel):
    id: str
    document_id: str
    chunk_index: int
    content: str | None  # omitted with include_content=false
    chars: int
    overlap_chars: int
    page_number: int | None
    page_end: int | None
    heading: str | None
    section: str | None
    headings: list[str]
    source: str | None
    source_type: str | None
    end_kind: str


class ChunkingInfo(BaseModel):
    chunker_version: str
    chunk_size: int
    chunk_overlap: int
    chunk_count: int
    pages: int | None
    noise_lines_removed: int
    built_at: datetime
    embedding_model: str | None = None  # Phase 2. None: not embedded (older build, or embedding failed)
    embedding_dim: int | None = None
    embedded_count: int = 0


class ChunksResponse(BaseModel):
    chunking: ChunkingInfo | None  # None: this set has no stored chunks yet (created before Phase 1b)
    chunks: list[ChunkOut]


class SearchHit(BaseModel):
    score: float  # what this mode ranks by (vector: cosine, keyword: BM25, hybrid: fused rank). Higher is better
    cosine: float | None  # similarity of meaning, None in keyword mode
    chunk: ChunkOut


class RebuildRequest(BaseModel):
    chunk_size: int | None = Field(default=None, ge=200, le=8000)
    chunk_overlap: int | None = Field(default=None, ge=0, le=4000)


def _out(row: dict, include_content: bool) -> ChunkOut:
    return ChunkOut(
        id=str(row["_id"]),
        document_id=str(row["document_id"]),
        chunk_index=row["chunk_index"],
        content=row["content"] if include_content else None,
        chars=row["chars"],
        overlap_chars=row["overlap_chars"],
        page_number=row["page_number"],
        page_end=row["page_end"],
        heading=row["heading"],
        section=row["section"],
        headings=row["headings"],
        source=row["source"],
        source_type=row["source_type"],
        end_kind=row["end_kind"],
    )


def _response(db: Database, doc: dict, include_content: bool) -> ChunksResponse:
    rows = db.chunks.find({"document_id": doc["_id"]}).sort("chunk_index", 1)
    return ChunksResponse(chunking=doc.get("chunking"), chunks=[_out(r, include_content) for r in rows])


@router.get("", response_model=ChunksResponse)
def get_chunks(
    set_id: str,
    include_content: bool = Query(True),
    db: Database = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    return _response(db, _get_set(db, set_id, user), include_content)


@router.post("/rebuild", response_model=ChunksResponse)
def rebuild_chunks(
    set_id: str,
    body: RebuildRequest | None = None,
    include_content: bool = Query(False),
    db: Database = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    doc = _get_set(db, set_id, user)
    body = body or RebuildRequest()
    current = doc.get("chunking") or {}  # a value you leave out stays as it was in the last build
    size = body.chunk_size if body.chunk_size is not None else current.get("chunk_size")
    overlap = body.chunk_overlap if body.chunk_overlap is not None else current.get("chunk_overlap")
    try:
        build_and_store(db, doc, size=size, overlap=overlap)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _response(db, _get_set(db, set_id, user), include_content)


@router.post("/embed", response_model=ChunksResponse)
def embed_chunks(
    set_id: str,
    include_content: bool = Query(False),
    db: Database = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Computes the embeddings of this set's stored chunks. Use it for sets made before Phase 2, or after a failure."""
    doc = _get_set(db, set_id, user)
    if not doc.get("chunking"):
        raise HTTPException(status_code=409, detail="This set has no chunks yet. Rebuild them first.")
    summary = embed_quietly(db, doc["_id"])
    if not summary["embedded_count"]:
        raise HTTPException(status_code=503, detail="Could not compute embeddings. See the server log.")
    db.notes.update_one({"_id": doc["_id"]}, {"$set": {f"chunking.{k}": v for k, v in summary.items()}})
    return _response(db, _get_set(db, set_id, user), include_content)


@router.get("/search", response_model=list[SearchHit])
def search(
    set_id: str,
    q: str = Query(..., min_length=2, max_length=500),
    k: int = Query(5, ge=1, le=20),
    mode: Mode = Query("hybrid"),
    include_content: bool = Query(True),
    db: Database = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    doc = _get_set(db, set_id, user)
    hits = search_hits(db, doc["_id"], q, k, mode)
    if not hits and not (doc.get("chunking") or {}).get("embedded_count"):
        raise HTTPException(status_code=409, detail="This set has no embeddings yet. POST .../chunks/embed first.")
    return [
        SearchHit(
            score=round(h.score, 4),
            cosine=None if h.cosine is None else round(h.cosine, 4),
            chunk=_out(h.row, include_content),
        )
        for h in hits
    ]
