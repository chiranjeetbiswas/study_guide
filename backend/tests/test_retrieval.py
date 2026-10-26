"""Tests for keyword, vector and hybrid search (RAG Phase 4). They need no database, server or AI.

Run from the backend folder:

    .venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.retrieval import bm25_scores, retrieve, rrf, tokenize  # noqa: E402


def row(text: str, vec: list[float]) -> dict:
    return {"content": text, "embedding": vec}


class TokenizeTests(unittest.TestCase):
    def test_lowercases_drops_stopwords_keeps_numbers_and_formulas(self):
        self.assertEqual(tokenize("What is the CO2 level in 1905?"), ["co2", "level", "1905"])

    def test_light_stemming_joins_word_forms(self):
        self.assertEqual(tokenize("cycles"), tokenize("cycle"))
        self.assertEqual(tokenize("boxes"), tokenize("box"))
        self.assertEqual(tokenize("batteries"), tokenize("battery"))
        self.assertEqual(tokenize("stomata pores"), ["stomata", "pore"])
        # endings that are part of the word, not a plural
        self.assertEqual(tokenize("glass photosynthesis"), ["glass", "photosynthesis"])


class Bm25Tests(unittest.TestCase):
    def test_rare_word_outweighs_common_word(self):
        docs = [tokenize(t) for t in ("plant cell wall", "plant leaf light", "plant root water", "rubisco enzyme plant")]
        scores = bm25_scores(tokenize("rubisco plant"), docs)
        self.assertEqual(scores.index(max(scores)), 3)

    def test_no_shared_word_scores_zero(self):
        self.assertEqual(bm25_scores(["xyz"], [["a", "b"], ["c"]]), [0.0, 0.0])

    def test_empty(self):
        self.assertEqual(bm25_scores(["a"], []), [])


class RrfTests(unittest.TestCase):
    def test_item_in_both_rankings_beats_item_in_one(self):
        fused = rrf([[0, 1, 2], [3, 1]])
        self.assertEqual(max(fused, key=fused.get), 1)

    def test_rank_one_beats_rank_two(self):
        fused = rrf([[7, 8]])
        self.assertGreater(fused[7], fused[8])


class RetrieveTests(unittest.TestCase):
    # Vectors are 2-D on purpose. Chunk 0 points along x, chunk 1 along y, chunk 2 sits between them.
    ROWS = [
        row("the enzyme rubisco fixes carbon", [1.0, 0.0]),
        row("sunlight is absorbed by pigments", [0.0, 1.0]),
        row("respiration releases energy", [0.7071, 0.7071]),
    ]

    def test_vector_mode_follows_meaning(self):
        hits = retrieve(self.ROWS, "anything", [0.0, 1.0], "vector", 3)
        self.assertEqual(hits[0].row["content"], "sunlight is absorbed by pigments")
        self.assertAlmostEqual(hits[0].cosine, 1.0, places=4)

    def test_keyword_mode_finds_exact_word_even_when_meaning_points_elsewhere(self):
        hits = retrieve(self.ROWS, "rubisco", None, "keyword", 3)
        self.assertEqual(len(hits), 1)  # chunks sharing no word are left out
        self.assertEqual(hits[0].row["content"], "the enzyme rubisco fixes carbon")
        self.assertIsNone(hits[0].cosine)

    def test_hybrid_rescues_what_vector_ranks_low(self):
        # The question vector points at chunk 1, but only chunk 0 contains the word asked about.
        vector_top = retrieve(self.ROWS, "rubisco", [0.0, 1.0], "vector", 3)
        hybrid_top = retrieve(self.ROWS, "rubisco", [0.0, 1.0], "hybrid", 3)
        self.assertEqual(vector_top[0].row["content"], "sunlight is absorbed by pigments")
        self.assertIn("rubisco", hybrid_top[0].row["content"])

    def test_same_input_same_order(self):
        a = [h.row["content"] for h in retrieve(self.ROWS, "energy", [1.0, 0.0], "hybrid", 3)]
        b = [h.row["content"] for h in retrieve(self.ROWS, "energy", [1.0, 0.0], "hybrid", 3)]
        self.assertEqual(a, b)

    def test_limits_and_errors(self):
        self.assertEqual(retrieve([], "x", [1.0, 0.0], "hybrid", 3), [])
        self.assertEqual(retrieve(self.ROWS, "x", [1.0, 0.0], "hybrid", 0), [])
        self.assertEqual(len(retrieve(self.ROWS, "x", [1.0, 0.0], "vector", 2)), 2)
        with self.assertRaises(ValueError):
            retrieve(self.ROWS, "x", None, "hybrid", 3)  # needs a vector
        with self.assertRaises(ValueError):
            retrieve(self.ROWS, "x", [1.0, 0.0], "bogus", 3)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
