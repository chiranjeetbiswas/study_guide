from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from pymongo.database import Database

from app import models, trace
from app.auth import get_current_user
from app.cards import CardOut, card_out
from app.checker import check_answers
from app.config import GROQ_API_KEY
from app.database import get_db
from app.extract import MAX_UPLOAD_BYTES, ExtractError, extract_text
from app.flashcards import MAX_NOTES_CHARS, NotesRequest, generate_flashcards

router = APIRouter(tags=["flashcards"])

MIN_NOTES_CHARS = 20


class GenerateResponse(BaseModel):
    note_id: str
    cards: list[CardOut]
    dropped: int  # cards removed because their source was not found in the notes


def generate_cards_for_note(db: Database, user: dict, note_id, notes: str, max_cards: int) -> GenerateResponse:
    """Generates, checks and saves cards for a note that already exists."""
    if not GROQ_API_KEY or GROQ_API_KEY.startswith(("paste-", "your-")):
        raise HTTPException(status_code=500, detail="GROQ_API_KEY is not set in backend/.env")
    with trace.traced(db, user, "flashcards", note_id, input_chars=len(notes)):
        try:
            result = generate_flashcards(notes, max_cards)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Flashcard generation failed: {type(e).__name__}")

        # Second Groq call: does each answer contain anything the source sentence doesn't say?
        checks = check_answers([(c.answer, c.source) for c in result.cards])
        trace.meta(cards_flagged_by_checker=sum(1 for c in checks if c.status != "supported"))

    card_docs = [
        models.new_card(
            note_id=note_id,
            user_id=user["_id"],
            question=c.question,
            answer=c.answer,
            source=c.source,
            check_status=check.status,
            check_reason=check.reason,
        )
        for c, check in zip(result.cards, checks)
    ]
    if card_docs:
        ids = db.cards.insert_many(card_docs).inserted_ids
        for doc, card_id in zip(card_docs, ids):
            doc["_id"] = card_id
    return GenerateResponse(note_id=str(note_id), cards=[card_out(d) for d in card_docs], dropped=result.dropped)


def _generate_and_save(db: Database, user: dict, notes: str, max_cards: int) -> GenerateResponse:
    note_id = db.notes.insert_one({"user_id": user["_id"], "text": notes, "created_at": models.now()}).inserted_id
    try:
        return generate_cards_for_note(db, user, note_id, notes, max_cards)
    except Exception:
        # No multi-document transaction on a standalone server, so undo the note by hand
        db.notes.delete_one({"_id": note_id})
        db.cards.delete_many({"note_id": note_id})
        raise


@router.post("/flashcards", response_model=GenerateResponse)
def flashcards(req: NotesRequest, db: Database = Depends(get_db), user: dict = Depends(get_current_user)):
    return _generate_and_save(db, user, req.notes, req.max_cards)


@router.post("/flashcards/upload", response_model=GenerateResponse)
def flashcards_from_file(
    file: UploadFile = File(...),
    max_cards: int = Form(10, ge=1, le=30),
    db: Database = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Same as POST /flashcards, but the notes come from an uploaded .pdf or .txt file."""
    data = file.file.read(MAX_UPLOAD_BYTES + 1)  # read one byte past the limit to detect oversize
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"File is too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB)")

    try:
        notes = extract_text(file.filename or "", data).strip()
    except ExtractError as e:
        raise HTTPException(status_code=422, detail=str(e))

    if len(notes) < MIN_NOTES_CHARS:
        raise HTTPException(status_code=422, detail="The file has too little text to make cards from.")
    if len(notes) > MAX_NOTES_CHARS:
        raise HTTPException(
            status_code=422,
            detail=f"The file has {len(notes):,} characters; the limit is {MAX_NOTES_CHARS:,}. Upload a shorter section.",
        )
    return _generate_and_save(db, user, notes, max_cards)
