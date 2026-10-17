from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from pymongo.database import Database

from app.auth import get_current_user
from app.cards import CardOut, _update_card, card_out, get_owned_card
from app.database import get_db
from app.models import CardStatus
from app.sm2 import next_schedule

router = APIRouter(tags=["quiz"])


class ReviewIn(BaseModel):
    knew: bool


@router.get("/quiz/due", response_model=list[CardOut])
def cards_due_today(db: Database = Depends(get_db), user: dict = Depends(get_current_user)):
    """Your approved cards that are due today or overdue (never-reviewed cards count as due)."""
    # ISO date strings compare correctly as text. {"due_date": None} would also match a missing field.
    query = {
        "user_id": user["_id"],
        "status": CardStatus.approved.value,
        "$or": [{"due_date": None}, {"due_date": {"$lte": date.today().isoformat()}}],
    }
    # Mongo sorts null before any string, so never-reviewed cards come first
    cursor = db.cards.find(query).sort([("due_date", 1), ("_id", 1)])
    return [card_out(doc) for doc in cursor]


@router.post("/cards/{card_id}/review", response_model=CardOut)
def review_card(
    card_id: str,
    review: ReviewIn,
    db: Database = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Records a quiz answer and reschedules the card with SM-2."""
    card = get_owned_card(db, card_id, user)
    if card["status"] != CardStatus.approved.value:
        raise HTTPException(status_code=400, detail="Only approved cards can be quizzed")

    s = next_schedule(card["ease_factor"], card["interval_days"], card["repetitions"], review.knew, date.today())
    updated = _update_card(
        db,
        card,
        {
            "ease_factor": s.ease_factor,
            "interval_days": s.interval_days,
            "repetitions": s.repetitions,
            "due_date": s.due_date.isoformat(),
        },
    )
    return card_out(updated)
