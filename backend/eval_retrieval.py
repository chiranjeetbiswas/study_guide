"""Measures how good retrieval is, so a change (chunk size, search mode) can be judged by numbers, not by feel.

    .venv\\Scripts\\python.exe eval_retrieval.py                      compare all search modes
    .venv\\Scripts\\python.exe eval_retrieval.py --chunk-size 600     try another chunk size
    .venv\\Scripts\\python.exe eval_retrieval.py --save samples\\baseline_eval.json
    .venv\\Scripts\\python.exe eval_retrieval.py --show-misses        list the questions each mode got wrong

For every question in samples/eval_questions.json it asks for the top results and checks whether one of them
contains the phrase that answers the question.

  hit@k   share of questions whose answer was inside the top k chunks (1.0 is perfect)
  MRR     mean of 1 / (position of the first correct chunk). 1.0 means always first, 0.5 means about second.

No server, database or AI key is needed. The notes are chunked and embedded in memory.
"""

import argparse
import json
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND))

from app.chunking import CHUNK_OVERLAP, CHUNK_SIZE, Page, chunk_document  # noqa: E402
from app.embeddings import EMBED_MODEL, embed_query, embed_texts  # noqa: E402
from app.extract import extract_document  # noqa: E402
from app.retrieval import MODES, retrieve  # noqa: E402

EVAL_SET = BACKEND / "samples" / "eval_questions.json"
KS = (1, 3, 5)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def load_eval_set(path: Path = EVAL_SET) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_rows(document: str, size: int, overlap: int) -> list[dict]:
    path = BACKEND / "samples" / document
    _, pages = extract_document(path.name, path.read_bytes())
    chunks = chunk_document([Page(i + 1, t) for i, t in enumerate(pages)], size=size, overlap=overlap).chunks
    vectors = embed_texts([c.content for c in chunks])
    return [{"content": c.content, "chunk_index": c.index, "embedding": v} for c, v in zip(chunks, vectors)]


def first_correct_position(hits: list, phrase: str) -> int | None:
    """1-based position of the first hit whose text contains the phrase, None if none does."""
    target = _norm(phrase)
    for pos, hit in enumerate(hits, start=1):
        if target in _norm(hit.row["content"]):
            return pos
    return None


def evaluate(rows: list[dict], questions: list[dict], mode: str) -> dict:
    """Metrics for one search mode: overall and per question kind."""
    positions = []
    for item in questions:
        hits = retrieve(rows, item["q"], embed_query(item["q"]), mode, max(KS))
        positions.append(first_correct_position(hits, item["answer_contains"]))

    def summarise(idx: list[int]) -> dict:
        pos = [positions[i] for i in idx]
        out = {f"hit@{k}": round(sum(1 for p in pos if p is not None and p <= k) / len(pos), 3) for k in KS}
        out["mrr"] = round(sum(1 / p for p in pos if p) / len(pos), 3)
        out["questions"] = len(pos)
        return out

    kinds = sorted({q["kind"] for q in questions})
    return {
        "overall": summarise(list(range(len(questions)))),
        "by_kind": {kind: summarise([i for i, q in enumerate(questions) if q["kind"] == kind]) for kind in kinds},
        "misses": [questions[i]["q"] for i, p in enumerate(positions) if p is None or p > max(KS)],
    }


def run(size: int, overlap: int) -> dict:
    data = load_eval_set()
    rows = build_rows(data["document"], size, overlap)
    return {
        "document": data["document"],
        "embedding_model": EMBED_MODEL,
        "chunk_size": size,
        "chunk_overlap": overlap,
        "chunks": len(rows),
        "modes": {mode: evaluate(rows, data["questions"], mode) for mode in MODES},
    }


def print_report(report: dict, show_misses: bool) -> None:
    print(
        f"{report['document']}: {report['chunks']} chunks "
        f"(size {report['chunk_size']}, overlap {report['chunk_overlap']}), model {report['embedding_model']}\n"
    )
    header = f"{'mode':<9}{'subset':<12}" + "".join(f"{'hit@' + str(k):>8}" for k in KS) + f"{'MRR':>8}{'n':>5}"
    print(header)
    print("-" * len(header))
    for mode, res in report["modes"].items():
        for name, m in [("all", res["overall"])] + list(res["by_kind"].items()):
            cells = "".join(f"{m[f'hit@{k}']:>8.2f}" for k in KS)
            print(f"{mode:<9}{name:<12}{cells}{m['mrr']:>8.2f}{m['questions']:>5}")
        print()
    if show_misses:
        for mode, res in report["modes"].items():
            print(f"{mode}: not in the top {max(KS)}: {res['misses'] or 'none'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate retrieval on samples/eval_questions.json")
    parser.add_argument("--chunk-size", type=int, default=CHUNK_SIZE)
    parser.add_argument("--chunk-overlap", type=int, default=CHUNK_OVERLAP)
    parser.add_argument("--save", help="write the numbers to this JSON file")
    parser.add_argument("--show-misses", action="store_true")
    args = parser.parse_args()

    report = run(args.chunk_size, args.chunk_overlap)
    print_report(report, args.show_misses)
    if args.save:
        Path(args.save).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"saved {args.save}")


if __name__ == "__main__":
    main()
