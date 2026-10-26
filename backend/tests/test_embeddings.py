"""Tests for embeddings and similarity search (RAG Phase 2).

Run from the backend folder, no server or database needed (the first run downloads the model, ~100 MB):

    .venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

import numpy as np

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.embeddings import EMBED_DIM, embed_query, embed_texts, rank  # noqa: E402

PASSAGES = [
    "Photosynthesis is how plants turn sunlight, water and carbon dioxide into glucose and oxygen.",
    "The French Revolution began in 1789 and ended the absolute monarchy in France.",
    "A binary search tree keeps smaller keys in the left subtree and larger keys in the right subtree.",
]


class EmbeddingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vectors = embed_texts(PASSAGES)
        cls.rows = [{"content": t, "embedding": v} for t, v in zip(PASSAGES, cls.vectors)]

    def test_shape_and_unit_length(self):
        self.assertEqual(len(self.vectors), len(PASSAGES))
        for v in self.vectors:
            self.assertEqual(len(v), EMBED_DIM)
            self.assertAlmostEqual(float(np.linalg.norm(v)), 1.0, places=4)

    def test_same_input_same_vector(self):
        again = embed_texts([PASSAGES[0]])[0]
        self.assertAlmostEqual(float(np.dot(again, self.vectors[0])), 1.0, places=4)

    def test_empty_input(self):
        self.assertEqual(embed_texts([]), [])

    def test_search_finds_the_right_passage(self):
        cases = {
            "How do plants make food from light?": 0,
            "When did the revolution in France start?": 1,
            "Where do larger keys go in a BST?": 2,
        }
        for question, expected in cases.items():
            top = rank(embed_query(question), self.rows, 1)[0][1]
            self.assertEqual(top["content"], PASSAGES[expected], question)

    def test_rank_order_and_limits(self):
        hits = rank(embed_query("plants and sunlight"), self.rows, 2)
        self.assertEqual(len(hits), 2)
        self.assertGreaterEqual(hits[0][0], hits[1][0])
        self.assertEqual(rank(embed_query("x"), self.rows, 0), [])
        self.assertEqual(rank(embed_query("x"), [{"content": "no vector"}], 3), [])


if __name__ == "__main__":
    unittest.main()
