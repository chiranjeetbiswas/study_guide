from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from pymongo import ReturnDocument
from pymongo.database import Database

from app.auth import get_current_user
from app.checker import check_answers
from app.database import get_db
from app.models import CardStatus, parse_id

router = APIRouter(prefix="/cards", tags=["cards"])


class CardOut(BaseModel):
    id: str
    note_id: str
    question: str
    answer: str
    source: str
    status: CardStatus
    created_at: datetime
    ease_factor: float
    interval_days: int
    repetitions: int
    due_date: date | None
    check_status: Literal["supported", "flagged"] | None
    check_reason: str | None


def card_out(doc: dict) -> CardOut:
    return CardOut(
        id=str(doc["_id"]),
        note_id=str(doc["note_id"]),
        question=doc["question"],
        answer=doc["answer"],
        source=doc["source"],
        status=doc["status"],
        created_at=doc["created_at"],
        ease_factor=doc["ease_factor"],
        interval_days=doc["interval_days"],
        repetitions=doc["repetitions"],
        due_date=doc["due_date"],  # ISO string or None; pydantic parses it into a date
        check_status=doc.get("check_status"),
        check_reason=doc.get("check_reason"),
    )


class CardEdit(BaseModel):
    # source is deliberately not editable: it must stay a verbatim quote from the notes
    question: str | None = Field(default=None, min_length=1)
    answer: str | None = Field(default=None, min_length=1)


def get_owned_card(db: Database, card_id: str, user: dict) -> dict:
    """Loads a card only if it belongs to the user. Someone else's card gets the same 404 as a missing one."""
    oid = parse_id(card_id)
    card = db.cards.find_one({"_id": oid, "user_id": user["_id"]}) if oid else None
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")
    return card


def _update_card(db: Database, card: dict, changes: dict) -> dict:
    return db.cards.find_one_and_update({"_id": card["_id"]}, {"$set": changes}, return_document=ReturnDocument.AFTER)


@router.get("", response_model=list[CardOut])
def list_cards(
    status: CardStatus = CardStatus.pending,
    db: Database = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Lists your cards with the given status (default: pending), oldest first."""
    cursor = db.cards.find({"user_id": user["_id"], "status": status.value}).sort([("created_at", 1), ("_id", 1)])
    return [card_out(doc) for doc in cursor]


@router.post("/{card_id}/approve", response_model=CardOut)
def approve_card(card_id: str, db: Database = Depends(get_db), user: dict = Depends(get_current_user)):
    card = get_owned_card(db, card_id, user)
    return card_out(_update_card(db, card, {"status": CardStatus.approved.value}))


@router.post("/{card_id}/reject", response_model=CardOut)
def reject_card(card_id: str, db: Database = Depends(get_db), user: dict = Depends(get_current_user)):
    card = get_owned_card(db, card_id, user)
    return card_out(_update_card(db, card, {"status": CardStatus.rejected.value}))


@router.patch("/{card_id}", response_model=CardOut)
def edit_card(
    card_id: str,
    edit: CardEdit,
    db: Database = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Edits question and/or answer. Status is left unchanged. A changed answer is re-checked against the source."""
    card = get_owned_card(db, card_id, user)
    changes = {}
    if edit.question is not None:
        changes["question"] = edit.question
    if edit.answer is not None and edit.answer != card["answer"]:
        changes["answer"] = edit.answer
        [result] = check_answers([(edit.answer, card["source"])])
        changes["check_status"], changes["check_reason"] = result.status, result.reason
    return card_out(_update_card(db, card, changes) if changes else card)
