"""Checks the evaluation set itself, so a typo in it cannot silently lower or inflate the retrieval numbers.

Every answer_contains phrase must really occur in the notes, and the retrieval quality must not fall below a floor.
The floors are set under the measured values (see samples/baseline_eval.json) so they catch a real regression
without failing on noise.

Run from the backend folder (the first run downloads the embedding model, ~100 MB):

    .venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.chunking import Page, chunk_document  # noqa: E402
from app.extract import extract_document  # noqa: E402
from eval_retrieval import _norm, evaluate, load_eval_set, build_rows  # noqa: E402
from app.chunking import CHUNK_OVERLAP, CHUNK_SIZE  # noqa: E402


class EvalSetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = load_eval_set()
        path = BACKEND / "samples" / cls.data["document"]
        _, pages = extract_document(path.name, path.read_bytes())
        cls.chunks = chunk_document([Page(i + 1, t) for i, t in enumerate(pages)]).chunks
        cls.rows = build_rows(cls.data["document"], CHUNK_SIZE, CHUNK_OVERLAP)

    def test_every_answer_phrase_is_in_the_notes(self):
        notes = _norm(" ".join(c.own_text for c in self.chunks))
        missing = [q["q"] for q in self.data["questions"] if _norm(q["answer_contains"]) not in notes]
        self.assertEqual(missing, [], "answer_contains must be copied from the notes")

    def test_questions_are_unique_and_have_a_known_kind(self):
        qs = [q["q"] for q in self.data["questions"]]
        self.assertEqual(len(qs), len(set(qs)))
        self.assertLessEqual({q["kind"] for q in self.data["questions"]}, {"paraphrase", "exact", "synonym"})

    def test_hybrid_search_quality_floor(self):
        overall = evaluate(self.rows, self.data["questions"], "hybrid")["overall"]
        self.assertGreaterEqual(overall["hit@5"], 0.9)
        self.assertGreaterEqual(overall["mrr"], 0.75)

    def test_hybrid_is_not_worse_than_vector_search(self):
        hybrid = evaluate(self.rows, self.data["questions"], "hybrid")["overall"]["mrr"]
        vector = evaluate(self.rows, self.data["questions"], "vector")["overall"]["mrr"]
        self.assertGreaterEqual(hybrid, vector)


if __name__ == "__main__":
    unittest.main()
