import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from pymongo.database import Database

from app import models, trace
from app.chunk_store import build_quietly
from app.ai import chat_json
from app.auth import get_current_user
from app.database import get_db
from app.documents import MAX_FILES, combined_text, default_title, files_of, make_file, unique_names
from app.extract import MAX_UPLOAD_BYTES, ExtractError, extract_document
from app.flashcards import MAX_NOTES_CHARS, _split_chunks
from app.generate import GenerateResponse, generate_cards_for_note

router = APIRouter(prefix="/sets", tags=["study sets"])

MIN_NOTES_CHARS = 20
REVISION_CHUNK_CHARS = 12_000
MAX_REVISION_CHUNKS = 15
# Quiz and paper prompts take the notes as they are up to this size; longer notes use the revision summary
DIRECT_CONTEXT_CHARS = 24_000

# Collection "notes" doubles as the study set. Extra fields on top of {user_id, text, created_at}:
#   title, subject, level (all optional text), revision (list of topics | None), quiz (list | None),
#   papers (list of generated exam papers, newest last)


# ---------- output shapes ----------


class FileInfo(BaseModel):
    name: str
    type: str  # "pdf" | "txt" | "text"
    chars: int
    pages: int | None  # PDFs only


class SetOut(BaseModel):
    id: str
    title: str
    subject: str
    level: str
    created_at: datetime
    chars: int
    has_revision: bool
    has_quiz: bool
    paper_count: int
    card_count: int
    files: list[FileInfo]  # the files the set was made from (up to 3)


class Term(BaseModel):
    term: str
    meaning: str


class Topic(BaseModel):
    title: str
    explanation: str  # plain-language explanation (may add clarity beyond the notes)
    key_points: list[str]  # taken from the notes
    terms: list[Term]
    likely_questions: list[str]


class QuizQuestion(BaseModel):
    question: str
    options: list[str]
    answer_index: int
    explanation: str


class PaperQuestion(BaseModel):
    number: int
    question: str
    marks: int
    options: list[str]  # empty unless it is a multiple-choice question
    answer: str
    marking_scheme: str


class PaperSection(BaseModel):
    name: str
    instructions: str
    questions: list[PaperQuestion]


class Paper(BaseModel):
    id: str
    created_at: datetime
    title: str
    total_marks: int
    duration_minutes: int | None
    instructions: list[str]
    sections: list[PaperSection]


class SetDetail(SetOut):
    revision: list[Topic] | None
    quiz: list[QuizQuestion] | None
    papers: list[Paper]


# ---------- helpers ----------


def _s(value, default: str = "") -> str:
    return value.strip() if isinstance(value, str) else default


def _str_list(value) -> list[str]:
    return [x.strip() for x in value if isinstance(x, str) and x.strip()] if isinstance(value, list) else []


def _default_title(text: str, subject: str) -> str:
    if subject:
        return subject
    first = " ".join(text.split())[:45]
    return first + ("…" if len(" ".join(text.split())) > 45 else "")


def _get_set(db: Database, set_id: str, user: dict) -> dict:
    oid = models.parse_id(set_id)
    doc = db.notes.find_one({"_id": oid, "user_id": user["_id"]}) if oid else None
    if doc is None:
        raise HTTPException(status_code=404, detail="Study set not found")
    return doc


def _set_out(doc: dict, card_count: int) -> SetOut:
    return SetOut(
        id=str(doc["_id"]),
        title=doc.get("title") or _default_title(doc["text"], doc.get("subject", "")),
        subject=doc.get("subject", ""),
        level=doc.get("level", ""),
        created_at=doc["created_at"],
        chars=len(doc["text"]),
        has_revision=bool(doc.get("revision")),
        has_quiz=bool(doc.get("quiz")),
        paper_count=len(doc.get("papers") or []),
        card_count=card_count,
        files=[
            FileInfo(name=f["name"], type=f["type"], chars=f["chars"], pages=len(f["pages"]) if f.get("pages") else None)
            for f in files_of(doc)
        ],
    )


def _detail(db: Database, doc: dict) -> SetDetail:
    count = db.cards.count_documents({"note_id": doc["_id"]})
    base = _set_out(doc, count)
    return SetDetail(
        **base.model_dump(),
        revision=doc.get("revision"),
        quiz=doc.get("quiz"),
        papers=doc.get("papers") or [],
    )


def _audience(doc: dict) -> str:
    parts = []
    if doc.get("subject"):
        parts.append(f"Subject: {doc['subject']}")
    if doc.get("level"):
        parts.append(f"Student level: {doc['level']} (adapt the wording and difficulty to this level)")
    return "\n".join(parts)


def _create(db: Database, user: dict, files: list[dict], title: str, subject: str, level: str) -> SetDetail:
    """Makes a study set from one to MAX_FILES files (see documents.py for what a file record holds)."""
    notes = combined_text(files)
    if len(notes) < MIN_NOTES_CHARS:
        raise HTTPException(status_code=422, detail="Notes are too short. Add at least a couple of sentences.")
    if len(notes) > MAX_NOTES_CHARS:
        raise HTTPException(
            status_code=422,
            detail=f"The notes have {len(notes):,} characters; the limit is {MAX_NOTES_CHARS:,}. Use shorter sections.",
        )
    title, subject, level = title.strip()[:100], subject.strip()[:100], level.strip()[:100]
    if not title:
        title = default_title(files) if len(files) > 1 and not subject else _default_title(notes, subject)
    doc = {
        "user_id": user["_id"],
        "text": notes,  # all files joined: what the AI features that read the whole notes get
        "created_at": models.now(),
        "title": title,
        "subject": subject,
        "level": level,
        "revision": None,
        "quiz": None,
        "papers": [],
        "files": files,  # kept per file: the chunker cleans and chunks each one on its own
    }
    doc["_id"] = db.notes.insert_one(doc).inserted_id
    build_quietly(db, doc)  # store this document's chunks (never blocks creation)
    return _detail(db, doc)


# ---------- create / list / read / delete ----------


class SetCreate(BaseModel):
    notes: str
    title: str = Field(default="", max_length=100)
    subject: str = Field(default="", max_length=100)
    level: str = Field(default="", max_length=100)


@router.post("", response_model=SetDetail, status_code=201)
def create_set(body: SetCreate, db: Database = Depends(get_db), user: dict = Depends(get_current_user)):
    return _create(db, user, [make_file("pasted text", "text", text=body.notes.strip())], body.title, body.subject, body.level)


@router.post("/upload", response_model=SetDetail, status_code=201)
def create_set_from_files(
    files: list[UploadFile] | None = File(None),  # 1 to MAX_FILES files, sent as repeated "files" fields
    file: UploadFile | None = File(None),  # a single file in the older "file" field still works
    title: str = Form(""),
    subject: str = Form(""),
    level: str = Form(""),
    db: Database = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    uploads = ([file] if file else []) + (files or [])
    if not uploads:
        raise HTTPException(status_code=422, detail="Add at least one file.")
    if len(uploads) > MAX_FILES:
        raise HTTPException(status_code=422, detail=f"You can add at most {MAX_FILES} files at a time.")

    names = unique_names([(u.filename or "file").strip() or "file" for u in uploads])
    records = []
    for upload, name in zip(uploads, names):
        data = upload.file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413, detail=f"{name}: file is too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB)"
            )
        try:
            text, pages = extract_document(name, data)
        except ExtractError as e:
            raise HTTPException(status_code=422, detail=f"{name}: {e}")
        records.append(make_file(name, "pdf" if pages else "txt", text=text, pages=pages))
    return _create(db, user, records, title, subject, level)


@router.get("", response_model=list[SetOut])
def list_sets(db: Database = Depends(get_db), user: dict = Depends(get_current_user)):
    counts = {
        row["_id"]: row["n"]
        for row in db.cards.aggregate(
            [{"$match": {"user_id": user["_id"]}}, {"$group": {"_id": "$note_id", "n": {"$sum": 1}}}]
        )
    }
    docs = db.notes.find({"user_id": user["_id"]}).sort("created_at", -1)
    return [_set_out(d, counts.get(d["_id"], 0)) for d in docs]


@router.get("/{set_id}", response_model=SetDetail)
def get_set(set_id: str, db: Database = Depends(get_db), user: dict = Depends(get_current_user)):
    return _detail(db, _get_set(db, set_id, user))


@router.delete("/{set_id}", status_code=204)
def delete_set(set_id: str, db: Database = Depends(get_db), user: dict = Depends(get_current_user)):
    doc = _get_set(db, set_id, user)
    db.cards.delete_many({"note_id": doc["_id"]})
    db.chunks.delete_many({"document_id": doc["_id"]})
    db.notes.delete_one({"_id": doc["_id"]})


# ---------- revision notes ----------

REVISION_PROMPT = """You turn a student's notes into clear revision notes for exam preparation.

Rules:
- Split the material into topics. Give each topic a short title.
- "key_points": the important facts, definitions, formulas and steps, taken from the notes. Keep them short. Do NOT invent facts that are not in the notes.
- "explanation": 2-4 sentences in simple, friendly words that help a student understand the topic. You may use a simple everyday comparison, but do not add new facts.
- "terms": important words from the notes with a short meaning (empty list if none).
- "likely_questions": 1-3 questions an examiner could ask on this topic.
- Cover every topic in the notes. Do not skip sections.

Respond with a JSON object only:
{"topics": [{"title": "...", "explanation": "...", "key_points": ["..."], "terms": [{"term": "...", "meaning": "..."}], "likely_questions": ["..."]}]}"""


def _parse_topics(data: dict) -> list[dict]:
    topics = []
    for t in data.get("topics", []):
        if not isinstance(t, dict) or not _s(t.get("title")):
            continue
        terms = [
            {"term": _s(x.get("term")), "meaning": _s(x.get("meaning"))}
            for x in (t.get("terms") or [])
            if isinstance(x, dict) and _s(x.get("term")) and _s(x.get("meaning"))
        ]
        topics.append(
            {
                "title": _s(t.get("title")),
                "explanation": _s(t.get("explanation")),
                "key_points": _str_list(t.get("key_points")),
                "terms": terms,
                "likely_questions": _str_list(t.get("likely_questions")),
            }
        )
    return topics


def _revision_for_chunk(chunk: str, audience: str) -> list[dict]:
    data = chat_json(REVISION_PROMPT, f"{audience}\n\nNOTES:\n{chunk}".strip(), max_tokens=8000, label="revision:chunk")
    topics = _parse_topics(data)
    trace.chunk_result(topics=len(topics))
    return topics


def _build_revision(db: Database, doc: dict) -> list[dict]:
    all_chunks = _split_chunks(doc["text"], REVISION_CHUNK_CHARS)
    chunks = all_chunks[:MAX_REVISION_CHUNKS]
    audience = _audience(doc)
    trace.meta(
        revision_chunk_chars=REVISION_CHUNK_CHARS,
        revision_max_chunks=MAX_REVISION_CHUNKS,
        chunks_total=len(all_chunks),
        chunks_used=len(chunks),
        chars_not_used=sum(len(c) for c in all_chunks[MAX_REVISION_CHUNKS:]),
    )

    def for_chunk(index: int, chunk: str):
        with trace.chunk_scope(index, chars=len(chunk)):
            return _revision_for_chunk(chunk, audience)

    with ThreadPoolExecutor(max_workers=min(2, len(chunks))) as pool:
        results = trace.map_in_context(pool, for_chunk, list(enumerate(chunks)))
    topics, seen = [], set()
    for chunk_topics in results:
        for t in chunk_topics:
            key = t["title"].lower()
            if key not in seen:
                seen.add(key)
                topics.append(t)
    if not topics:
        raise HTTPException(status_code=422, detail="Couldn't build revision notes from this text. Try adding more detail.")
    db.notes.update_one({"_id": doc["_id"]}, {"$set": {"revision": topics}})
    trace.meta(topics_total=len(topics), topics_before_title_dedupe=sum(len(r) for r in results))
    return topics


@router.post("/{set_id}/revision", response_model=SetDetail)
def make_revision(set_id: str, db: Database = Depends(get_db), user: dict = Depends(get_current_user)):
    doc = _get_set(db, set_id, user)
    with trace.traced(db, user, "revision", doc["_id"], input_chars=len(doc["text"])):
        _build_revision(db, doc)
    return _detail(db, _get_set(db, set_id, user))


def _context(db: Database, doc: dict) -> str:
    """The material quiz and paper prompts work from: the notes themselves, or a summary when they are long."""
    if len(doc["text"]) <= DIRECT_CONTEXT_CHARS:
        trace.meta(context_source="full_notes", context_chars=len(doc["text"]), direct_context_limit=DIRECT_CONTEXT_CHARS)
        return doc["text"]
    had_revision = bool(doc.get("revision"))
    topics = doc.get("revision") or _build_revision(db, doc)
    lines = []
    for t in topics:
        lines.append(f"## {t['title']}")
        lines.extend(f"- {p}" for p in t["key_points"])
        lines.extend(f"- {x['term']}: {x['meaning']}" for x in t["terms"])
    summary = "\n".join(lines)
    context = summary[:DIRECT_CONTEXT_CHARS * 2]
    trace.meta(
        context_source="revision_summary",
        revision_existed_before=had_revision,
        direct_context_limit=DIRECT_CONTEXT_CHARS,
        summary_chars=len(summary),
        context_chars=len(context),
        context_truncated_chars=len(summary) - len(context),
    )
    return context


# ---------- quiz ----------

QUIZ_PROMPT = """You write multiple-choice quiz questions for a student, using ONLY the material given.

Rules:
- Exactly 4 options per question, exactly one correct. Wrong options must be believable but clearly wrong according to the material.
- "answer_index" is the position (0-3) of the correct option. Spread the correct answers across positions.
- "explanation": one or two sentences saying why the answer is right.
- Cover different topics from the material. Do not repeat questions.
- Do not use facts that are not in the material.

Respond with a JSON object only:
{"questions": [{"question": "...", "options": ["A", "B", "C", "D"], "answer_index": 0, "explanation": "..."}]}"""


class QuizRequest(BaseModel):
    count: int = Field(default=10, ge=3, le=30)


@router.post("/{set_id}/quiz", response_model=SetDetail)
def make_quiz(
    set_id: str, body: QuizRequest, db: Database = Depends(get_db), user: dict = Depends(get_current_user)
):
    doc = _get_set(db, set_id, user)
    with trace.traced(db, user, "quiz", doc["_id"], input_chars=len(doc["text"]), questions_requested=body.count):
        context = _context(db, doc)
        data = chat_json(
            QUIZ_PROMPT,
            f"{_audience(doc)}\n\nWrite {body.count} questions.\n\nMATERIAL:\n{context}".strip(),
            max_tokens=8000,
            label="quiz",
        )
        questions = []
        for q in data.get("questions", []):
            if not isinstance(q, dict):
                continue
            options = _str_list(q.get("options"))
            idx = q.get("answer_index")
            if _s(q.get("question")) and len(options) == 4 and isinstance(idx, int) and 0 <= idx < 4:
                questions.append(
                    {
                        "question": _s(q.get("question")),
                        "options": options,
                        "answer_index": idx,
                        "explanation": _s(q.get("explanation")),
                    }
                )
        trace.meta(questions_valid=len(questions))
    if not questions:
        raise HTTPException(status_code=422, detail="Couldn't build quiz questions from this text. Try again.")
    db.notes.update_one({"_id": doc["_id"]}, {"$set": {"quiz": questions[: body.count]}})
    return _detail(db, _get_set(db, set_id, user))


# ---------- exam paper ----------

PAPER_PROMPT = """You are an examiner. Write an exam question paper using ONLY the material given.

Rules:
- The marks of all questions must add up to EXACTLY the total marks requested.
- Divide the paper into sections by question type, for example: Section A multiple choice (1 mark each), Section B short answer (2-5 marks), Section C long answer (5+ marks). Choose a sensible mix for the total marks and the student level. Follow the extra details from the user if given.
- Multiple-choice questions have exactly 4 options in "options" and the correct one stated in "answer". Other questions have "options": [].
- "answer": a correct model answer. "marking_scheme": how the marks are awarded (for example "1 mark for definition, 1 mark for example").
- Number questions continuously from 1 across sections.
- Cover the whole material fairly. Do not use facts that are not in the material.

Respond with a JSON object only:
{"title": "...", "instructions": ["..."], "sections": [{"name": "Section A", "instructions": "...", "questions": [{"number": 1, "question": "...", "marks": 1, "options": ["..."], "answer": "...", "marking_scheme": "..."}]}]}"""


class PaperRequest(BaseModel):
    total_marks: int = Field(ge=5, le=200)
    duration_minutes: int | None = Field(default=None, ge=5, le=600)
    details: str = Field(default="", max_length=1000)  # optional: difficulty, chapters, question types...


def _parse_paper(data: dict, req: PaperRequest) -> dict | None:
    sections, number = [], 1
    for s in data.get("sections", []):
        if not isinstance(s, dict):
            continue
        questions = []
        for q in s.get("questions", []):
            marks = q.get("marks") if isinstance(q, dict) else None
            if not isinstance(marks, int) or marks < 1 or not _s(q.get("question")):
                continue
            options = _str_list(q.get("options"))
            questions.append(
                {
                    "number": number,
                    "question": _s(q.get("question")),
                    "marks": marks,
                    "options": options if len(options) >= 2 else [],
                    "answer": _s(q.get("answer")),
                    "marking_scheme": _s(q.get("marking_scheme")),
                }
            )
            number += 1
        if questions:
            sections.append({"name": _s(s.get("name"), "Questions"), "instructions": _s(s.get("instructions")), "questions": questions})
    if not sections:
        return None
    return {
        "id": uuid.uuid4().hex,
        "created_at": models.now(),
        "title": _s(data.get("title"), "Exam paper"),
        "total_marks": req.total_marks,
        "duration_minutes": req.duration_minutes,
        "instructions": _str_list(data.get("instructions")),
        "sections": sections,
    }


def _marks_sum(paper: dict) -> int:
    return sum(q["marks"] for s in paper["sections"] for q in s["questions"])


@router.post("/{set_id}/paper", response_model=SetDetail)
def make_paper(
    set_id: str, body: PaperRequest, db: Database = Depends(get_db), user: dict = Depends(get_current_user)
):
    doc = _get_set(db, set_id, user)
    with trace.traced(
        db, user, "paper", doc["_id"], input_chars=len(doc["text"]), total_marks=body.total_marks, details=body.details
    ):
        context = _context(db, doc)
        request_text = f"{_audience(doc)}\n\nTotal marks: {body.total_marks}"
        if body.duration_minutes:
            request_text += f"\nDuration: {body.duration_minutes} minutes (size the paper to fit)"
        if body.details.strip():
            request_text += f"\nExtra details from the user: {body.details.strip()}"
        request_text += f"\n\nMATERIAL:\n{context}"

        paper = None
        for attempt in range(2):
            feedback = ""
            if paper is not None:
                feedback = (
                    f"\n\nYour previous paper added up to {_marks_sum(paper)} marks but it must be exactly "
                    f"{body.total_marks}. Fix the marks."
                )
            data = chat_json(PAPER_PROMPT, request_text + feedback, max_tokens=10000, label=f"paper:attempt{attempt + 1}")
            candidate = _parse_paper(data, body)
            if candidate is None:
                continue
            paper = candidate
            if _marks_sum(paper) == body.total_marks:
                break
        if paper is not None:
            trace.meta(marks_sum_before_fix=_marks_sum(paper), attempts=attempt + 1)
    if paper is None:
        raise HTTPException(status_code=422, detail="Couldn't build an exam paper from this text. Try again.")

    # Still off after the retry: put the difference on the last question rather than show a wrong total
    diff = body.total_marks - _marks_sum(paper)
    if diff:
        last = paper["sections"][-1]["questions"][-1]
        if last["marks"] + diff >= 1:
            last["marks"] += diff

    db.notes.update_one({"_id": doc["_id"]}, {"$push": {"papers": paper}})
    return _detail(db, _get_set(db, set_id, user))


@router.delete("/{set_id}/paper/{paper_id}", response_model=SetDetail)
def delete_paper(set_id: str, paper_id: str, db: Database = Depends(get_db), user: dict = Depends(get_current_user)):
    doc = _get_set(db, set_id, user)
    db.notes.update_one({"_id": doc["_id"]}, {"$pull": {"papers": {"id": paper_id}}})
    return _detail(db, _get_set(db, set_id, user))


# ---------- flashcards for this set ----------


class FlashcardsRequest(BaseModel):
    max_cards: int = Field(default=10, ge=1, le=30)


@router.post("/{set_id}/flashcards", response_model=GenerateResponse)
def make_flashcards(
    set_id: str, body: FlashcardsRequest, db: Database = Depends(get_db), user: dict = Depends(get_current_user)
):
    doc = _get_set(db, set_id, user)
    return generate_cards_for_note(db, user, doc["_id"], doc["text"], body.max_cards)
