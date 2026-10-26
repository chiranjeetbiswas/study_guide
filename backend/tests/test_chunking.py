"""Tests for the structured chunker (RAG Phase 1b) and for the guarantee that the old chunker did not change.

Run from the backend folder, no server or database needed:

    .venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""

import json
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.chunking import CHUNK_OVERLAP, CHUNK_SIZE, OVERLAP_SEP, Page, chunk_document, split_sentences  # noqa: E402
from app.extract import extract_document, extract_text  # noqa: E402
from app.flashcards import _split_chunks  # noqa: E402

SAMPLE = BACKEND / "samples" / "sample_notes.pdf"
BASELINE = BACKEND / "samples" / "baseline_sample_notes.json"


def sample_pages() -> list[Page]:
    _, pages = extract_document(SAMPLE.name, SAMPLE.read_bytes())
    return [Page(i + 1, t) for i, t in enumerate(pages)]


def nonspace(text: str) -> int:
    return sum(1 for ch in text if not ch.isspace())


class StructuredChunkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = chunk_document(sample_pages())

    def test_every_character_ends_up_in_a_chunk(self):
        in_blocks = sum(nonspace(b.text) for b in self.result.blocks)
        in_chunks = sum(nonspace(c.own_text) for c in self.result.chunks)
        self.assertEqual(in_blocks, in_chunks)

    def test_size_limits(self):
        for c in self.result.chunks:
            self.assertLessEqual(len(c.own_text), CHUNK_SIZE, f"chunk {c.index} new text too long")
            self.assertLessEqual(len(c.content), CHUNK_SIZE + CHUNK_OVERLAP + len(OVERLAP_SEP))

    def test_no_heading_is_stranded_at_the_end_of_a_chunk(self):
        for c in self.result.chunks[:-1]:
            self.assertNotEqual(c.block_kinds[-1], "heading", f"chunk {c.index} ends with a heading")

    def test_overlap_is_the_end_of_the_previous_chunk(self):
        chunks = self.result.chunks
        self.assertEqual(chunks[0].overlap_chars, 0)
        for prev, cur in zip(chunks, chunks[1:]):
            self.assertGreater(cur.overlap_chars, 0)
            self.assertLessEqual(cur.overlap_chars, CHUNK_OVERLAP)
            overlap = cur.content[: cur.overlap_chars]
            self.assertTrue(prev.own_text.rstrip().endswith(overlap), f"chunk {cur.index} overlap is not a tail of chunk {prev.index}")

    def test_running_footer_is_removed(self):
        self.assertEqual(sum(n["times"] for n in self.result.noise_removed), 3)
        for c in self.result.chunks:
            self.assertNotIn("Chapter 6 Notes - Page", c.content)

    def test_page_numbers_are_kept_and_never_go_backwards(self):
        numbers = [c.page_number for c in self.result.chunks]
        self.assertTrue(all(n is not None for n in numbers))
        self.assertEqual(numbers[0], 1)
        self.assertEqual(self.result.chunks[-1].page_end or self.result.chunks[-1].page_number, 3)
        self.assertEqual(numbers, sorted(numbers))

    def test_headings_and_sections_are_detected(self):
        first = self.result.chunks[0]
        self.assertEqual(first.section, "Chapter 6: Life Processes - Photosynthesis and Respiration")
        self.assertIn("1. Introduction to Photosynthesis", first.headings)
        sections = {c.section for c in self.result.chunks}
        self.assertIn("2. The Two Stages of Photosynthesis", sections)

    def test_deterministic(self):
        again = chunk_document(sample_pages())
        self.assertEqual([c.content for c in self.result.chunks], [c.content for c in again.chunks])

    def test_smaller_size_gives_more_chunks(self):
        counts = [len(chunk_document(sample_pages(), size=s, overlap=0).chunks) for s in (600, 1200, 2400)]
        self.assertGreater(counts[0], counts[1])
        self.assertGreater(counts[1], counts[2])

    def test_no_chunk_is_only_a_heading_at_any_size(self):
        for size in (200, 300, 400, 600, 800, 1200, 2400):
            result = chunk_document(sample_pages(), size=size, overlap=0)
            for c in result.chunks:
                self.assertNotEqual(set(c.block_kinds), {"heading"}, f"size {size}: chunk {c.index} is only headings")
                self.assertLessEqual(len(c.own_text), size + 200, f"size {size}: chunk {c.index} far over the limit")

    def test_overlap_zero_means_no_repeated_text(self):
        result = chunk_document(sample_pages(), size=1200, overlap=0)
        for c in result.chunks:
            self.assertEqual(c.overlap_chars, 0)
            self.assertEqual(c.content, c.own_text)


class EdgeCaseTests(unittest.TestCase):
    def test_pasted_text_has_no_invented_metadata(self):
        text = "Plants make food using sunlight. They take in carbon dioxide and release oxygen. " * 40
        result = chunk_document([Page(None, text)], size=400, overlap=50)
        self.assertGreater(len(result.chunks), 1)
        for c in result.chunks:
            self.assertIsNone(c.page_number)
            self.assertIsNone(c.page_end)
            self.assertIsNone(c.heading)
            self.assertIsNone(c.section)

    def test_empty_text_gives_no_chunks(self):
        self.assertEqual(chunk_document([Page(None, "  \n\n ")]).chunks, [])

    def test_bad_settings_are_rejected(self):
        with self.assertRaises(ValueError):
            chunk_document([Page(None, "x " * 200)], size=100)
        with self.assertRaises(ValueError):
            chunk_document([Page(None, "x " * 200)], size=400, overlap=300)

    def test_one_huge_sentence_is_split_at_word_boundaries(self):
        text = " ".join(f"word{i}" for i in range(2000))  # no punctuation at all
        result = chunk_document([Page(None, text)], size=500, overlap=0)
        self.assertGreater(len(result.chunks), 5)
        for c in result.chunks:
            self.assertLessEqual(len(c.own_text), 500)
        self.assertEqual(" ".join(c.own_text for c in result.chunks).split(), text.split())

    def test_abbreviations_do_not_split_sentences(self):
        text = "Dr. Joseph Priestley used a mint plant, e.g. in a jar (see Fig. 1). F. F. Blackman came later. It worked."
        self.assertEqual(
            split_sentences(text),
            [
                "Dr. Joseph Priestley used a mint plant, e.g. in a jar (see Fig. 1).",
                "F. F. Blackman came later.",
                "It worked.",
            ],
        )

    def test_hyphenated_line_ends_are_rejoined(self):
        result = chunk_document([Page(None, "Photo-\nsynthesis makes food for the plant.")], size=400, overlap=0)
        self.assertIn("Photosynthesis makes food", result.chunks[0].content)

    def test_paragraph_across_a_page_break_is_one_block_with_both_pages(self):
        pages = [Page(1, "Plants need light and water and also"), Page(2, "carbon dioxide to make food.")]
        result = chunk_document(pages, size=400, overlap=0)
        self.assertEqual(len(result.blocks), 1)
        self.assertEqual((result.blocks[0].page_start, result.blocks[0].page_end), (1, 2))
        self.assertEqual((result.chunks[0].page_number, result.chunks[0].page_end), (1, 2))

    def test_heading_stays_with_the_text_that_follows_it(self):
        body = "This sentence is filler text about plants. " * 25
        text = f"{body}\n\n1. Light Reactions\nLight is absorbed by chlorophyll."
        result = chunk_document([Page(None, text)], size=1000, overlap=0)
        holder = [c for c in result.chunks if "1. Light Reactions" in c.content][0]
        self.assertIn("Light is absorbed", holder.content)


class OldChunkerUnchangedTests(unittest.TestCase):
    """Phase 1a recorded how the old chunker splits the sample. Phase 1b must not change that."""

    def test_old_chunker_still_matches_the_phase_1a_baseline(self):
        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))["profiles"]["flashcards"]
        text = extract_text(SAMPLE.name, SAMPLE.read_bytes()).strip()
        sizes = [len(c) for c in _split_chunks(text, 6000)]
        self.assertEqual(sizes, [c["chars"] for c in baseline["chunks"]])

    def test_extract_document_text_equals_extract_text(self):
        data = SAMPLE.read_bytes()
        self.assertEqual(extract_document(SAMPLE.name, data)[0], extract_text(SAMPLE.name, data))


if __name__ == "__main__":
    unittest.main()
