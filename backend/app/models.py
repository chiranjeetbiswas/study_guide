import enum
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId


class CardStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


# Collections (documents are plain dicts):
#
# users: {_id, name (optional, absent on older accounts), email (unique, stored lowercase), password_hash (Argon2id, never the password), created_at}
#
# notes: {_id, user_id, text, created_at}
#
# cards: {_id, note_id, user_id, question, answer, source, status, created_at,
#         check_status ("supported" | "flagged" | None = never checked), check_reason,
#         ease_factor, interval_days, repetitions, due_date}
#   - user_id is copied from the note so ownership checks need no join
#   - due_date is an ISO "YYYY-MM-DD" string (Mongo has no date-only type); None means "never reviewed, due now"


def now() -> datetime:
    return datetime.now(timezone.utc)


def parse_id(value: str) -> ObjectId | None:
    """ObjectId from a string, or None if it isn't a valid one (so callers can answer 404 instead of 500)."""
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


def new_card(*, note_id: ObjectId, user_id: ObjectId, question: str, answer: str, source: str,
             check_status: str | None, check_reason: str | None) -> dict:
    return {
        "note_id": note_id,
        "user_id": user_id,
        "question": question,
        "answer": answer,
        "source": source,
        "status": CardStatus.pending.value,
        "created_at": now(),
        "check_status": check_status,
        "check_reason": check_reason,
        "ease_factor": 2.5,
        "interval_days": 0,
        "repetitions": 0,
        "due_date": None,
    }
