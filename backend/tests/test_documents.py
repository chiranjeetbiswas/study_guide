"""Tests for study sets made from several files (up to 3): records, combined text and per-file chunking.
No server, database or AI is needed.

Run from the backend folder:

    .venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.chunk_store import chunk_files  # noqa: E402
from app.chunking import CHUNK_OVERLAP, CHUNK_SIZE, Page, chunk_document  # noqa: E402
from app.documents import (  # noqa: E402
    MAX_FILES,
    combined_text,
    default_title,
    file_text,
    files_of,
    make_file,
    unique_names,
)
from app.extract import extract_document  # noqa: E402

SAMPLES = BACKEND / "samples"


def pdf_file(name: str):
    text, pages = extract_document(name, (SAMPLES / name).read_bytes())
    return make_file(name, "pdf", text=text, pages=pages), text


NOTE = (
    "Zebraxq stripes are unique to each animal. The zebraxq herd migrates every year.\n\n"
    "A second paragraph about the zebraxq keeps this file long enough to produce a chunk of its own. " * 3
)


class RecordTests(unittest.TestCase):
    def test_limit_is_three(self):
        self.assertEqual(MAX_FILES, 3)

    def test_pdf_record_keeps_pages_and_text_is_their_join(self):
        f = make_file("a.pdf", "pdf", pages=["one", "two"])
        self.assertEqual(f["pages"], [{"number": 1, "text": "one"}, {"number": 2, "text": "two"}])
        self.assertIsNone(f["text"])
        self.assertEqual(file_text(f), "one\ntwo")
        self.assertEqual(f["chars"], 7)

    def test_text_record(self):
        f = make_file("n.txt", "txt", text="hello")
        self.assertEqual((f["pages"], file_text(f), f["chars"]), (None, "hello", 5))

    def test_single_file_text_has_no_source_line(self):
        f = make_file("a.pdf", "pdf", pages=["one", "two"])
        self.assertEqual(combined_text([f]), "one\ntwo")  # exactly what a single-file set always had

    def test_several_files_are_joined_in_order_with_source_lines(self):
        a, b = make_file("a.txt", "txt", text="AAA"), make_file("b.txt", "txt", text="BBB")
        self.assertEqual(combined_text([a, b]), "[Source: a.txt]\nAAA\n\n[Source: b.txt]\nBBB")

    def test_legacy_sets_without_files_still_work(self):
        pdf = {"text": "one\ntwo", "source_name": "old.pdf", "source_type": "pdf", "source_pages": [{"number": 1, "text": "one"}, {"number": 2, "text": "two"}]}
        (f,) = files_of(pdf)
        self.assertEqual((f["name"], f["type"], len(f["pages"]), f["chars"]), ("old.pdf", "pdf", 2, 7))
        pasted = {"text": "just notes"}
        (g,) = files_of(pasted)
        self.assertEqual((g["name"], g["type"], file_text(g)), ("pasted text", "text", "just notes"))

    def test_new_sets_use_their_files(self):
        f = make_file("a.txt", "txt", text="x")
        self.assertEqual(files_of({"text": "x", "files": [f]}), [f])

    def test_unique_names(self):
        self.assertEqual(unique_names(["a.pdf", "b.pdf", "A.pdf", "a.pdf"]), ["a.pdf", "b.pdf", "A (2).pdf", "a (3).pdf"])
        self.assertEqual(unique_names(["notes", "notes"]), ["notes", "notes (2)"])

    def test_default_title_from_file_names(self):
        files = [make_file("Biology.pdf", "pdf", pages=["x"]), make_file("Chemistry notes.txt", "txt", text="y")]
        self.assertEqual(default_title(files), "Biology, Chemistry notes")
        self.assertLessEqual(len(default_title([make_file("x" * 80 + ".pdf", "pdf", pages=["x"])] * 3)), 100)


class ChunkFilesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bio, bio_text = pdf_file("sample_notes.pdf")
        cls.long, _ = pdf_file("sample_notes_long.pdf")
        cls.zebra = make_file("zebra.txt", "txt", text=NOTE)
        cls.files = [cls.bio, cls.zebra, cls.long]
        cls.chunks, cls.per_file, cls.noise, cls.pdf_pages = chunk_files(cls.files, CHUNK_SIZE, CHUNK_OVERLAP)
        cls.bio_text = bio_text

    def test_single_file_gives_exactly_the_chunks_it_always_did(self):
        chunks, per_file, _, pages = chunk_files([self.bio], CHUNK_SIZE, CHUNK_OVERLAP)
        _, raw_pages = extract_document("sample_notes.pdf", (SAMPLES / "sample_notes.pdf").read_bytes())
        expected = chunk_document([Page(i + 1, t) for i, t in enumerate(raw_pages)]).chunks
        self.assertEqual([c["content"] for c in chunks], [c.content for c in expected])
        self.assertEqual([c["page_number"] for c in chunks], [c.page_number for c in expected])
        self.assertEqual((len(per_file), pages), (1, 3))

    def test_chunk_numbers_run_on_across_files_without_gaps(self):
        self.assertEqual([c["chunk_index"] for c in self.chunks], list(range(len(self.chunks))))

    def test_every_chunk_knows_its_file_and_files_stay_in_upload_order(self):
        order = []
        for c in self.chunks:
            if not order or order[-1] != c["source"]:
                order.append(c["source"])
        self.assertEqual(order, ["sample_notes.pdf", "zebra.txt", "sample_notes_long.pdf"])
        types = {c["source"]: c["source_type"] for c in self.chunks}
        self.assertEqual(types, {"sample_notes.pdf": "pdf", "zebra.txt": "txt", "sample_notes_long.pdf": "pdf"})

    def test_no_chunk_mixes_text_from_two_files(self):
        for c in self.chunks:
            has_zebra = "zebraxq" in c["content"].lower()
            self.assertEqual(has_zebra, c["source"] == "zebra.txt", c["source"])

    def test_page_numbers_restart_in_each_file(self):
        first_page = {}
        for c in self.chunks:
            first_page.setdefault(c["source"], c["page_number"])
        self.assertEqual(first_page["sample_notes.pdf"], 1)
        self.assertEqual(first_page["sample_notes_long.pdf"], 1)  # not 4, which it would be if pages ran on
        self.assertIsNone(first_page["zebra.txt"])  # a text file has no pages

    def test_summary_adds_up(self):
        self.assertEqual([f["name"] for f in self.per_file], ["sample_notes.pdf", "zebra.txt", "sample_notes_long.pdf"])
        self.assertEqual(sum(f["chunks"] for f in self.per_file), len(self.chunks))
        self.assertEqual([f["pages"] for f in self.per_file], [3, None, 9])
        self.assertEqual(self.pdf_pages, 12)

    def test_bad_settings_still_raise(self):
        with self.assertRaises(ValueError):
            chunk_files(self.files, 50, 0)


if __name__ == "__main__":
    unittest.main()
