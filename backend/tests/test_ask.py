"""Tests for the parts of "ask your notes" (RAG Phase 3) that need neither the AI nor the database.

Run from the backend folder:

    .venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.ask import (  # noqa: E402
    SNIPPET_CHARS,
    Turn,
    _history_text,
    _prompt_sources,
    _source,
    _standalone_question,
    _used_numbers,
)
from app.retrieval import Hit  # noqa: E402


class UsedNumbersTests(unittest.TestCase):
    def test_keeps_valid_numbers_in_order_without_duplicates(self):
        self.assertEqual(_used_numbers([3, 1, 3, 2], 5), [3, 1, 2])

    def test_drops_out_of_range_and_wrong_types(self):
        self.assertEqual(_used_numbers([0, 6, -1, "2", 2.0, True, None, 4], 5), [4])

    def test_not_a_list(self):
        for raw in (None, "1", 3, {"a": 1}):
            self.assertEqual(_used_numbers(raw, 5), [])


class PromptSourcesTests(unittest.TestCase):
    def test_numbers_sources_and_adds_where_it_came_from(self):
        hits = [
            Hit({"content": "alpha", "heading": "Intro", "page_number": 2}, 0.9, 0.9),
            Hit({"content": "beta", "heading": None, "page_number": None}, 0.8, 0.8),
        ]
        text = _prompt_sources(hits)
        self.assertIn("[1] (Intro, page 2)\nalpha", text)
        self.assertIn("[2]\nbeta", text)


class SourceTests(unittest.TestCase):
    def test_snippet_is_cut_but_text_is_whole(self):
        row = {"content": "x" * (SNIPPET_CHARS + 50), "chunk_index": 4, "page_number": None, "heading": None}
        s = _source(2, Hit(row, 0.5, 0.123456))
        self.assertEqual((s.number, s.chunk_index, s.score), (2, 4, 0.1235))
        self.assertTrue(s.snippet.endswith("…"))
        self.assertEqual(len(s.text), SNIPPET_CHARS + 50)

    def test_short_chunk_has_no_ellipsis(self):
        s = _source(1, Hit({"content": "short", "chunk_index": 0, "page_number": 1, "heading": "H"}, 1.0, None))
        self.assertEqual(s.snippet, "short")
        self.assertIsNone(s.score)  # keyword mode has no similarity


class MemoryTests(unittest.TestCase):
    def test_no_history_needs_no_ai_call(self):
        self.assertEqual(_standalone_question([], "what is x?"), "what is x?")

    def test_history_text_keeps_only_recent_turns_and_cuts_long_answers(self):
        turns = [Turn(question=f"q{i}", answer="a" * 2000) for i in range(6)]
        text = _history_text(turns)
        self.assertNotIn("q2", text)
        self.assertIn("q3", text)
        self.assertIn("q5", text)
        self.assertLess(len(text), 3 * 700)


if __name__ == "__main__":
    unittest.main()
