"""Tests for the generate, review, retry loop (RAG Phase 5). The generator and reviewer are fakes, so no AI is called.

Run from the backend folder:

    .venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

from fastapi import HTTPException

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.ask import _draft_from  # noqa: E402
from app.verify import MAX_ATTEMPTS, Draft, Review, feedback_for_generator, parse_review, verify_loop  # noqa: E402


class FakeGenerator:
    """Returns the given drafts one after another and remembers the feedback each call was given."""

    def __init__(self, *drafts: Draft):
        self.drafts = list(drafts)
        self.feedback: list[str | None] = []

    def __call__(self, feedback):
        self.feedback.append(feedback)
        return self.drafts[min(len(self.feedback), len(self.drafts)) - 1]


def good(text="Right."):
    return Draft(True, text, [1])


class FakeReviewer:
    def __init__(self, *verdicts):
        self.verdicts = list(verdicts)
        self.calls = 0

    def __call__(self, draft):
        self.calls += 1
        v = self.verdicts[min(self.calls, len(self.verdicts)) - 1]
        if isinstance(v, Exception):
            raise v
        return v


OK = Review(True, [])
BAD = Review(False, ["claim X - not in the sources"])


class LoopTests(unittest.TestCase):
    def test_verified_on_the_first_attempt(self):
        gen, rev = FakeGenerator(good()), FakeReviewer(OK)
        out = verify_loop(gen, rev)
        self.assertEqual((out.status, out.attempts, rev.calls), ("verified", 1, 1))
        self.assertEqual(gen.feedback, [None])  # the first attempt gets no feedback

    def test_rejected_answer_is_regenerated_with_feedback_then_verified(self):
        gen = FakeGenerator(good("wrong"), good("right"))
        rev = FakeReviewer(BAD, OK)
        out = verify_loop(gen, rev)
        self.assertEqual((out.status, out.attempts), ("verified", 2))
        self.assertEqual(out.draft.answer, "right")
        self.assertIsNone(gen.feedback[0])
        self.assertIn("claim X", gen.feedback[1])
        self.assertIn("wrong", gen.feedback[1])  # the generator is shown what it said before
        self.assertEqual([r.supported for r in out.rounds], [False, True])

    def test_gives_up_after_max_attempts_and_keeps_the_last_answer(self):
        gen = FakeGenerator(good("a1"), good("a2"), good("a3"), good("a4"))
        rev = FakeReviewer(BAD)
        out = verify_loop(gen, rev)
        self.assertEqual(out.status, "unverified")
        self.assertEqual(out.attempts, MAX_ATTEMPTS)
        self.assertEqual(len(gen.feedback), MAX_ATTEMPTS)  # never more than the limit
        self.assertEqual(out.draft.answer, "a3")
        self.assertEqual(len(out.rounds), MAX_ATTEMPTS)

    def test_max_attempts_can_be_changed(self):
        gen, rev = FakeGenerator(good()), FakeReviewer(BAD)
        self.assertEqual(verify_loop(gen, rev, max_attempts=1).attempts, 1)
        self.assertEqual(rev.calls, 1)

    def test_not_covered_answer_is_not_reviewed(self):
        gen, rev = FakeGenerator(Draft(False, "The notes do not cover this.")), FakeReviewer(BAD)
        out = verify_loop(gen, rev)
        self.assertEqual((out.status, rev.calls), ("not_applicable", 0))

    def test_generator_can_decide_on_retry_that_the_notes_do_not_cover_it(self):
        gen = FakeGenerator(good("invented"), Draft(False, "The notes do not cover this."))
        out = verify_loop(gen, FakeReviewer(BAD))
        self.assertEqual(out.status, "not_applicable")
        self.assertFalse(out.draft.found)

    def test_reviewer_outage_does_not_block_the_answer(self):
        gen = FakeGenerator(good())
        out = verify_loop(gen, FakeReviewer(HTTPException(status_code=502, detail="down")))
        self.assertEqual((out.status, out.attempts, out.draft.answer), ("unchecked", 1, "Right."))
        self.assertIsNone(out.rounds[0].supported)

    def test_unusable_review_counts_as_unchecked(self):
        out = verify_loop(FakeGenerator(good()), FakeReviewer(None))
        self.assertEqual(out.status, "unchecked")


class ParseReviewTests(unittest.TestCase):
    def test_supported(self):
        self.assertEqual(parse_review({"verdict": "supported", "issues": []}), Review(True, []))

    def test_unsupported_keeps_issues(self):
        r = parse_review({"verdict": "unsupported", "issues": ["  a  ", "", 5, "b"]})
        self.assertEqual(r, Review(False, ["a", "b"]))

    def test_supported_with_issues_is_treated_as_unsupported(self):
        self.assertFalse(parse_review({"verdict": "supported", "issues": ["something"]}).supported)

    def test_unsupported_without_issues_still_gets_a_reason_for_the_generator(self):
        r = parse_review({"verdict": "unsupported"})
        self.assertFalse(r.supported)
        self.assertEqual(len(r.issues), 1)

    def test_unusable(self):
        for data in ({}, {"verdict": "maybe"}, {"verdict": None, "issues": []}):
            self.assertIsNone(parse_review(data))

    def test_issue_count_and_length_are_capped(self):
        r = parse_review({"verdict": "unsupported", "issues": ["x" * 1000] * 20})
        self.assertEqual(len(r.issues), 5)
        self.assertEqual(len(r.issues[0]), 300)

    def test_feedback_lists_the_problems(self):
        text = feedback_for_generator("old answer", ["p1", "p2"])
        for part in ("old answer", "- p1", "- p2"):
            self.assertIn(part, text)


class DraftFromTests(unittest.TestCase):
    def test_found_answer(self):
        self.assertEqual(_draft_from({"found": True, "answer": " Yes. ", "used": [2, 9]}, 3), Draft(True, "Yes.", [2]))

    def test_found_without_sources_cited_shows_all_sources(self):
        self.assertEqual(_draft_from({"found": True, "answer": "Yes.", "used": []}, 3).used, [1, 2, 3])

    def test_not_found_or_empty_answer(self):
        self.assertFalse(_draft_from({"found": False, "answer": "no"}, 3).found)
        self.assertFalse(_draft_from({"found": True, "answer": "  "}, 3).found)
        self.assertFalse(_draft_from({}, 3).found)


if __name__ == "__main__":
    unittest.main()
