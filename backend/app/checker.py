import json
from dataclasses import dataclass

from groq import Groq

from app.config import GROQ_API_KEY
from app.flashcards import MODEL
from app.trace import traced_create

SUPPORTED = "supported"
FLAGGED = "flagged"

SYSTEM_PROMPT = """You are a strict fact-checker for flashcards.

For each item you get a SOURCE sentence and an ANSWER. Decide whether the ANSWER contains any information that is NOT stated in, or directly implied by, the SOURCE.

- "flagged": the answer adds ANY fact, number, name, date, cause, example or detail that the source does not contain, or it contradicts the source.
- "supported": every claim in the answer is stated in or directly implied by the source. Rewording and shortening are fine.

Judge only against the SOURCE. Do not use your own knowledge to decide whether something is true.
Give a short reason (max 20 words). For flagged items, name the unsupported information.

Respond with a JSON object only:
{"results": [{"id": 0, "verdict": "supported" | "flagged", "reason": "..."}]}
Return exactly one result per input item, using the same ids."""


@dataclass
class CheckResult:
    status: str
    reason: str


def _unverified(reason: str) -> CheckResult:
    # Fail safe: if we couldn't verify a card, a human should look at it
    return CheckResult(FLAGGED, reason)


def check_answers(items: list[tuple[str, str]]) -> list[CheckResult]:
    """items are (answer, source) pairs. Returns one CheckResult per item, in order."""
    if not items:
        return []

    payload = [{"id": i, "source": source, "answer": answer} for i, (answer, source) in enumerate(items)]

    try:
        client = Groq(api_key=GROQ_API_KEY, max_retries=6)
        completion = traced_create(
            client,
            "cards:check",
            model=MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload)},
            ],
        )
        raw = json.loads(completion.choices[0].message.content)
        returned = {r["id"]: r for r in raw.get("results", []) if isinstance(r, dict) and "id" in r}
    except Exception:
        return [_unverified("Automatic check failed; please verify manually.") for _ in items]

    results = []
    for i in range(len(items)):
        r = returned.get(i)
        verdict = r.get("verdict") if r else None
        if verdict not in (SUPPORTED, FLAGGED):
            results.append(_unverified("No check result returned; please verify manually."))
        else:
            reason = str(r.get("reason") or "").strip()[:300]
            results.append(CheckResult(verdict, reason or ("Answer matches the source." if verdict == SUPPORTED else "Answer may go beyond the source.")))
    return results
