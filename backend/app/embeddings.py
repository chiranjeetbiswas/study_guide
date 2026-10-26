"""Turns chunks into vectors and finds the chunks closest to a question (RAG Phase 2).

    chunks (Phase 1b)  -->  embed each chunk's content  -->  store the vector on the chunk  -->  similarity search

The model runs locally (fastembed + ONNX): no API key, no cost. The first use downloads it (~100 MB) into
EMBED_CACHE_DIR, later runs load it from there. The model is loaded once, on first use, not at import time,
so starting the server stays fast and works even if the model is not downloaded yet.

Each chunk document gets two more fields (the rest of the chunk is described in chunk_store.py):
    embedding         list of floats, length = EMBED_DIM, unit length (so similarity is a plain dot product)
    embedding_model   which model made it. Vectors from different models are NOT comparable, so search only
                      looks at chunks embedded with the current model. Change EMBED_MODEL and re-embed.
"""

import logging
import os
import threading
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from pymongo.database import Database

load_dotenv()

log = logging.getLogger("embeddings")

EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
EMBED_DIM = 384  # output size of EMBED_MODEL. Change it together with the model.
# Kept inside the project (git-ignored), not in the Windows temp folder, which gets cleaned up.
EMBED_CACHE_DIR = os.getenv("EMBED_CACHE_DIR", str(Path(__file__).resolve().parent.parent / ".model_cache"))
EMBED_BATCH = 32

_model = None
_lock = threading.Lock()


def _get_model():
    global _model
    with _lock:
        if _model is None:
            from fastembed import TextEmbedding  # imported here: slow import, and optional until first use

            log.info("loading embedding model %s", EMBED_MODEL)
            _model = TextEmbedding(model_name=EMBED_MODEL, cache_dir=EMBED_CACHE_DIR)
        return _model


def _unit(vectors) -> list[list[float]]:
    arr = np.asarray(list(vectors), dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (arr / norms).tolist()


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Vectors for passages (chunk contents), in the same order."""
    if not texts:
        return []
    return _unit(_get_model().embed(texts, batch_size=EMBED_BATCH))


def embed_query(question: str) -> list[float]:
    """Vector for a search question. bge models are trained to treat questions slightly differently from passages."""
    return _unit(_get_model().query_embed(question))[0]


def embed_document_chunks(db: Database, document_id) -> dict:
    """Embeds every chunk of one document and stores the vectors. Returns a summary for notes.chunking."""
    rows = list(db.chunks.find({"document_id": document_id}, {"content": 1}).sort("chunk_index", 1))
    vectors = embed_texts([r["content"] for r in rows])
    for row, vec in zip(rows, vectors):
        db.chunks.update_one({"_id": row["_id"]}, {"$set": {"embedding": vec, "embedding_model": EMBED_MODEL}})
    return {"embedding_model": EMBED_MODEL, "embedding_dim": EMBED_DIM, "embedded_count": len(rows)}


def rank(query_vec: list[float], rows: list[dict], k: int) -> list[tuple[float, dict]]:
    """The k rows whose embedding is most similar to query_vec, best first, as (score, row). Pure function."""
    rows = [r for r in rows if r.get("embedding")]
    if not rows or k <= 0:
        return []
    scores = np.asarray([r["embedding"] for r in rows], dtype=np.float32) @ np.asarray(query_vec, dtype=np.float32)
    order = np.argsort(-scores)[:k]
    return [(float(scores[i]), rows[i]) for i in order]


def search_chunks(db: Database, document_id, question: str, k: int = 5) -> list[tuple[float, dict]]:
    """The k chunks of one document that best match the question. Scores are cosine similarity (-1 to 1)."""
    rows = list(db.chunks.find({"document_id": document_id, "embedding_model": EMBED_MODEL}))
    return rank(embed_query(question), rows, k)
