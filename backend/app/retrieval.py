"""Finding the chunks that answer a question: keyword search, meaning search, or both (RAG Phase 4).

  keyword   BM25 over the words of each chunk. Good at exact things: names, numbers, formulas, terms like "RuBisCO".
  vector    cosine similarity of embeddings (embeddings.py). Good at paraphrases: "why are leaves green" finds
            "green light is reflected" although they share no words.
  hybrid    both, merged with Reciprocal Rank Fusion. Each method ranks the chunks, and a chunk scores
            sum(1 / (RRF_K + rank)) over the rankings it appears in. Only ranks are used, so the two very different
            score scales (BM25 is unbounded, cosine is -1..1) never have to be compared. A chunk both methods like
            wins over a chunk only one of them likes.

Everything here is a plain function on lists of chunk rows, with no database and no AI, so the evaluation script
(eval_retrieval.py) and the API (ask.py, chunks_api.py) run exactly the same code. `search` is the one function that
touches the database: it loads the chunks of a document and calls `retrieve`.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Literal

import numpy as np
from pymongo.database import Database

from app.embeddings import EMBED_MODEL, embed_query

Mode = Literal["hybrid", "vector", "keyword"]
MODES: tuple[str, ...] = ("hybrid", "vector", "keyword")

BM25_K1 = 1.5  # how quickly repeating a word stops adding to the score
BM25_B = 0.75  # how much a long chunk is penalised against a short one
RRF_K = 60  # the usual constant: it keeps the first few ranks from dominating the sum
POOL = 20  # in hybrid mode, how many results each method contributes before merging

# Words that say nothing about a topic. Short on purpose: BM25 already gives common words a low weight.
STOPWORDS = frozenset(
    "a an and are as at be been but by can did do does for from had has have how i if in into is it its of on or "
    "so than that the their them then there these they this to was we were what when where which who whom why will "
    "with would you your".split()
)

_WORD = re.compile(r"[a-z0-9]+")


@dataclass
class Hit:
    row: dict
    score: float  # what the chunks were ranked by in this mode (higher is better)
    cosine: float | None  # similarity to the question, None when the query was not embedded (keyword mode)


def _stem(word: str) -> str:
    """Very light suffix stripping so plurals and verb forms meet: pores/pore, cycles/cycle, boxes/box, bubbles/bubble.
    It is not a real stemmer. It only has to give a word and its variants the same token on both sides of a search."""
    if len(word) > 5 and word.endswith("ing"):
        return word[:-3]
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith(("sses", "xes", "zes", "ches", "shes")):
        return word[:-2]
    if len(word) > 4 and word.endswith("ed"):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def tokenize(text: str) -> list[str]:
    return [_stem(w) for w in _WORD.findall(text.lower()) if w not in STOPWORDS]


def bm25_scores(query_tokens: list[str], docs_tokens: list[list[str]]) -> list[float]:
    """BM25 score of every document for the query, in the same order as docs_tokens."""
    n = len(docs_tokens)
    if n == 0:
        return []
    lengths = [len(d) for d in docs_tokens]
    avg_len = (sum(lengths) / n) or 1.0
    doc_freq: Counter = Counter()
    for d in docs_tokens:
        doc_freq.update(set(d))
    counts = [Counter(d) for d in docs_tokens]
    scores = []
    for tf, length in zip(counts, lengths):
        s = 0.0
        for term in set(query_tokens):
            f = tf.get(term, 0)
            if not f:
                continue
            idf = math.log(1 + (n - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5))
            s += idf * f * (BM25_K1 + 1) / (f + BM25_K1 * (1 - BM25_B + BM25_B * length / avg_len))
        scores.append(s)
    return scores


def _order(scores: list[float]) -> list[int]:
    """Indexes best first. Ties keep reading order, so results are the same on every run."""
    return sorted(range(len(scores)), key=lambda i: (-scores[i], i))


def rrf(rankings: list[list[int]], k: int = RRF_K) -> dict[int, float]:
    """Reciprocal Rank Fusion: item -> sum of 1 / (k + rank) over the rankings that contain it (rank starts at 1)."""
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            fused[item] = fused.get(item, 0.0) + 1.0 / (k + rank)
    return fused


def retrieve(
    rows: list[dict], question: str, query_vec: list[float] | None, mode: Mode = "hybrid", k: int = 5
) -> list[Hit]:
    """The k best chunks for the question, best first. `rows` are chunk documents (content, and embedding for
    the vector and hybrid modes). query_vec may be None in keyword mode."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    if not rows or k <= 0:
        return []
    if mode != "keyword" and query_vec is None:
        raise ValueError("this mode needs the question as a vector")

    cosine: dict[int, float] = {}
    if query_vec is not None:
        embedded = [i for i, r in enumerate(rows) if r.get("embedding")]
        if embedded:
            sims = np.asarray([rows[i]["embedding"] for i in embedded], dtype=np.float32) @ np.asarray(query_vec, dtype=np.float32)
            cosine = {i: float(s) for i, s in zip(embedded, sims)}

    keyword_scores = bm25_scores(tokenize(question), [tokenize(r["content"]) for r in rows])
    # A chunk with a score of 0 shares no word with the question. Leaving it out keeps noise out of the fusion.
    keyword_rank = [i for i in _order(keyword_scores) if keyword_scores[i] > 0]
    vector_rank = sorted(cosine, key=lambda i: (-cosine[i], i))

    if mode == "keyword":
        scored = [(i, keyword_scores[i]) for i in keyword_rank]
    elif mode == "vector":
        scored = [(i, cosine[i]) for i in vector_rank]
    else:
        fused = rrf([vector_rank[:POOL], keyword_rank[:POOL]])
        scored = sorted(fused.items(), key=lambda kv: (-kv[1], kv[0]))
    return [Hit(rows[i], float(score), cosine.get(i)) for i, score in scored[:k]]


def search(db: Database, document_id, question: str, k: int = 5, mode: Mode = "hybrid") -> list[Hit]:
    """retrieve() over the stored chunks of one document. Chunks embedded with another model are skipped,
    because their vectors cannot be compared with this model's."""
    rows = list(db.chunks.find({"document_id": document_id, "embedding_model": EMBED_MODEL}).sort("chunk_index", 1))
    return retrieve(rows, question, embed_query(question) if mode != "keyword" else None, mode, k)
