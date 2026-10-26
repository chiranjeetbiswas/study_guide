"""Measures the whole answer pipeline: retrieve, generate, fact-check, retry (RAG Phase 5).

    .venv\\Scripts\\python.exe eval_answers.py                  run everything (about 2-4 minutes, ~120 AI calls)
    .venv\\Scripts\\python.exe eval_answers.py --limit 8        quick run on the first 8 + 2 unanswerable questions
    .venv\\Scripts\\python.exe eval_answers.py --save samples\\baseline_answer_eval.json

For each question in samples/eval_questions.json the script runs the same code as the Ask tab (retrieval.retrieve,
ask._generate, ask._review, verify.verify_loop). A separate judge call then compares the answer with the notes
passage that holds the correct answer.

  answerable questions (the notes contain the answer)
    retrieval hit     the passage with the answer was among the retrieved chunks
    without the loop  the FIRST answer the generator wrote: what you get with "Fact-check answers" off
    with the loop     the FINAL answer after review and retries: what the student sees
    verified          the reviewer found every claim in the notes (first try, or after at most 3 attempts)
  unanswerable questions (the notes do not contain the answer)
    refused           the answer says the notes do not cover it, instead of guessing

The judge is the same model as the generator and the reviewer, so treat the numbers as a strong signal, not proof.
Needs GROQ_API_KEY in backend/.env. No server or database is used.
"""

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BACKEND = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND))

from app.ai import chat_json  # noqa: E402
from app.ask import TOP_K, _generate, _prompt_sources, _review  # noqa: E402
from app.chunking import CHUNK_OVERLAP, CHUNK_SIZE  # noqa: E402
from app.config import REVIEW_MODEL  # noqa: E402
from app.embeddings import EMBED_MODEL, embed_query  # noqa: E402
from app.retrieval import retrieve  # noqa: E402
from app.verify import MAX_ATTEMPTS, Draft, verify_loop  # noqa: E402
from eval_retrieval import _norm, build_rows, load_eval_set  # noqa: E402

RETRIES = 6  # a question that hit the rate limit is run again, after waiting
WAIT_SECONDS = 30  # the limit is per minute, so half a minute usually clears it
JUDGE_MODEL = os.getenv("EVAL_JUDGE_MODEL") or None  # unset: the default model. Set it to spread the load over two models
WORKERS = int(os.getenv("EVAL_WORKERS", "1"))  # questions run at once. Groq's per-minute token limit is the real cap

JUDGE_PROMPT = """You grade a student-help chatbot. You get a QUESTION, a REFERENCE passage from the student's notes that contains the correct answer, and the chatbot's ANSWER.

Mark the ANSWER correct only if it states the key fact the REFERENCE gives for this question and does not contradict the REFERENCE. Different wording is fine. Extra detail is fine if it does not contradict the REFERENCE. An answer that only says the notes do not cover the question is NOT correct.

Respond with a JSON object only: {"correct": true, "reason": "<one short sentence>"}"""


def judge(question: str, reference: str, answer: str) -> bool:
    data = chat_json(
        JUDGE_PROMPT,
        f"QUESTION:\n{question}\n\nREFERENCE:\n{reference}\n\nANSWER:\n{answer}",
        max_tokens=300,
        label="eval:judge",
        model=JUDGE_MODEL,
    )
    return data.get("correct") is True


def run_pipeline(rows: list[dict], question: str) -> dict:
    """The Ask tab's pipeline, recording every draft the generator wrote."""
    hits = retrieve(rows, question, embed_query(question), "hybrid", TOP_K)
    sources_text, count = _prompt_sources(hits), len(hits)
    drafts: list[Draft] = []

    def generate(feedback):
        draft = _generate(sources_text, question, feedback, count)
        drafts.append(draft)
        return draft

    outcome = verify_loop(generate, lambda d: _review(sources_text, question, d))
    return {"hits": hits, "drafts": drafts, "outcome": outcome}


def eval_answerable(rows: list[dict], item: dict) -> dict:
    question, phrase = item["q"], _norm(item["answer_contains"])
    gold = [r["content"] for r in rows if phrase in _norm(r["content"])]
    reference = "\n---\n".join(gold[:2])
    try:
        run = run_pipeline(rows, question)
        first, final, outcome = run["drafts"][0], run["outcome"].draft, run["outcome"]
        first_ok = first.found and judge(question, reference, first.answer)
        # The final answer is the first one unless the loop replaced it: no second judge call needed then.
        final_ok = first_ok if final is first else (final.found and judge(question, reference, final.answer))
    except Exception as e:  # one failed API call must not lose the whole run
        return {"q": question, "error": f"{type(e).__name__}: {getattr(e, 'detail', e)}"[:200]}
    return {
        "q": question,
        "kind": item["kind"],
        "retrieval_hit": any(phrase in _norm(h.row["content"]) for h in run["hits"]),
        "first_correct": bool(first_ok),
        "final_correct": bool(final_ok),
        "status": outcome.status,
        "attempts": outcome.attempts,
        "final_answer": final.answer,
        "issues": [r.issues for r in outcome.rounds if r.issues],
    }


def eval_unanswerable(rows: list[dict], question: str) -> dict:
    try:
        run = run_pipeline(rows, question)
    except Exception as e:
        return {"q": question, "error": f"{type(e).__name__}: {getattr(e, 'detail', e)}"[:200]}
    return {
        "q": question,
        "first_refused": not run["drafts"][0].found,
        "final_refused": not run["outcome"].draft.found,
        "final_answer": run["outcome"].draft.answer,
    }


def patiently(run, *args) -> dict:
    """Runs one question again (after a wait) while the API rate limit gets in the way. A result is unusable when
    the question failed with an API error, or when the reviewer could not run (status 'unchecked'): the loop
    deliberately lets the student through in that case, but an evaluation must not count it as a result."""
    for attempt in range(RETRIES):
        result = run(*args)
        if "error" not in result and result.get("status") != "unchecked":
            return result
        if attempt < RETRIES - 1:
            time.sleep(WAIT_SECONDS)
    return result


def pct(n: int, total: int) -> str:
    return f"{n}/{total} ({100 * n / total:.0f}%)" if total else "n/a"


def summarise(answerable: list[dict], unanswerable: list[dict]) -> dict:
    ok = [r for r in answerable if "error" not in r]
    un = [r for r in unanswerable if "error" not in r]
    return {
        "answerable": len(ok),
        "retrieval_hit": sum(r["retrieval_hit"] for r in ok),
        "first_correct": sum(r["first_correct"] for r in ok),
        "final_correct": sum(r["final_correct"] for r in ok),
        "verified": sum(r["status"] == "verified" for r in ok),
        "verified_first_try": sum(r["status"] == "verified" and r["attempts"] == 1 for r in ok),
        "needed_retry": sum(r["attempts"] > 1 for r in ok),
        "unverified": sum(r["status"] == "unverified" for r in ok),
        "unchecked": sum(r["status"] == "unchecked" for r in ok),
        "refused_wrongly": sum(r["status"] == "not_applicable" for r in ok),
        "mean_attempts": round(sum(r["attempts"] for r in ok) / len(ok), 2) if ok else None,
        "fixed_by_loop": sum((not r["first_correct"]) and r["final_correct"] for r in ok),
        "broken_by_loop": sum(r["first_correct"] and not r["final_correct"] for r in ok),
        "unanswerable": len(un),
        "first_refused": sum(r["first_refused"] for r in un),
        "final_refused": sum(r["final_refused"] for r in un),
        "errors": len(answerable) - len(ok) + len(unanswerable) - len(un),
    }


def print_report(s: dict, answerable: list[dict]) -> None:
    n = s["answerable"]
    print(f"\nAnswerable questions: {n}   (generator and reviewer: up to {MAX_ATTEMPTS} attempts)")
    print(f"  answer passage retrieved        {pct(s['retrieval_hit'], n)}")
    print(f"  correct WITHOUT the loop        {pct(s['first_correct'], n)}   (first answer only)")
    print(f"  correct WITH the loop           {pct(s['final_correct'], n)}   (what the student sees)")
    print(f"  verified by the reviewer        {pct(s['verified'], n)}   ({s['verified_first_try']} on the first try)")
    print(f"  needed at least one retry       {pct(s['needed_retry'], n)}")
    print(f"  still unverified after {MAX_ATTEMPTS}        {pct(s['unverified'], n)}")
    print(f"  review did not run (API error)  {pct(s['unchecked'], n)}   (should be 0, otherwise rerun)")
    print(f"  refused although answerable     {pct(s['refused_wrongly'], n)}")
    print(f"  wrong answers fixed by the loop {s['fixed_by_loop']}    correct answers broken by it {s['broken_by_loop']}")
    print(f"  mean attempts per question      {s['mean_attempts']}")
    u = s["unanswerable"]
    print(f"\nUnanswerable questions: {u}")
    print(f"  refused at the first answer     {pct(s['first_refused'], u)}")
    print(f"  refused after the loop          {pct(s['final_refused'], u)}")
    if s["errors"]:
        print(f"\n{s['errors']} question(s) failed with an API error and are left out of the numbers above.")
    wrong = [r for r in answerable if "error" not in r and not r["final_correct"]]
    if wrong:
        print("\nAnswers judged wrong or refused:")
        for r in wrong:
            print(f"  - {r['q']}  [{r['status']}, attempts {r['attempts']}]\n      {r['final_answer'][:160]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the full answer pipeline")
    parser.add_argument("--limit", type=int, help="only the first N answerable questions (and 2 unanswerable)")
    parser.add_argument("--save", help="write results to this JSON file")
    args = parser.parse_args()

    data = load_eval_set()
    rows = build_rows(data["document"], CHUNK_SIZE, CHUNK_OVERLAP)
    questions, unanswerable = data["questions"], data["unanswerable"]
    if args.limit:
        questions, unanswerable = questions[: args.limit], unanswerable[:2]
    print(f"{data['document']}: {len(rows)} chunks, embeddings {EMBED_MODEL}. Reviewer model: {REVIEW_MODEL or 'same as generator'}, judge model: {JUDGE_MODEL or 'same as generator'}.")
    print(f"Running {len(questions) + len(unanswerable)} questions…")

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        ans = list(pool.map(lambda it: patiently(eval_answerable, rows, it), questions))
        unans = list(pool.map(lambda q: patiently(eval_unanswerable, rows, q), unanswerable))

    summary = summarise(ans, unans)
    print_report(summary, ans)
    if args.save:
        Path(args.save).write_text(
            json.dumps({"summary": summary, "answerable": ans, "unanswerable": unans}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\nsaved {args.save}")


if __name__ == "__main__":
    main()
