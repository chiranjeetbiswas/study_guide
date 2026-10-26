"""Read-only debugging endpoints for the RAG pipeline (Phase 1a).

  POST /debug/chunks               inspect how any pasted text or uploaded file is chunked (nothing is saved)
  GET  /debug/sets/{id}/chunks     inspect how a saved study set is chunked
  GET  /debug/runs                 recent generation runs (Groq calls, latency, tokens, chunks used)
  GET  /debug/runs/{run_id}        one run in full

Everything is scoped to the logged-in user. Nothing here changes any generation behaviour.
"""

from datetime import datetime
from typing import Literal

from bson import ObjectId
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pymongo.database import Database

from app.auth import get_current_user
from app.database import get_db
from app.extract import MAX_UPLOAD_BYTES, ExtractError
from app.inspector import extract_with_pages, inspect_document
from app.models import parse_id
from app.studyset import _get_set

router = APIRouter(prefix="/debug", tags=["debug"])

Profile = Literal["both", "flashcards", "revision"]


def _profiles(profile: str) -> tuple[str, ...]:
    return ("flashcards", "revision") if profile == "both" else (profile,)


def _jsonable(value):
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items() if k != "user_id"}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


@router.post("/chunks")
def inspect_upload(
    file: UploadFile | None = File(None),
    text: str = Form(""),
    profile: Profile = Form("both"),
    preview_chars: int = Form(150, ge=20, le=1000),
    user: dict = Depends(get_current_user),
):
    """Inspect a file or pasted text without saving it."""
    if file is not None:
        data = file.file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="File is too large")
        try:
            body, spans = extract_with_pages(file.filename or "", data)
        except ExtractError as e:
            raise HTTPException(status_code=422, detail=str(e))
        name = file.filename or "upload"
    elif text.strip():
        body, spans, name = text.strip(), None, "pasted text"
    else:
        raise HTTPException(status_code=422, detail="Send a file or some text")
    return inspect_document(body, name=name, page_spans=spans, preview_chars=preview_chars, profiles=_profiles(profile))


@router.get("/sets/{set_id}/chunks")
def inspect_set(
    set_id: str,
    profile: Profile = "both",
    preview_chars: int = Query(150, ge=20, le=1000),
    db: Database = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    doc = _get_set(db, set_id, user)
    name = doc.get("title") or "study set"
    return inspect_document(doc["text"], name=name, preview_chars=preview_chars, profiles=_profiles(profile))


@router.get("/runs")
def list_runs(
    set_id: str | None = None,
    kind: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    db: Database = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    query: dict = {"user_id": user["_id"]}
    if set_id:
        oid = parse_id(set_id)
        if oid is None:
            raise HTTPException(status_code=404, detail="Study set not found")
        query["set_id"] = oid
    if kind:
        query["kind"] = kind
    rows = db.generation_runs.find(query, {"calls": 0, "chunks": 0}).sort("created_at", -1).limit(limit)
    return [_jsonable(r) for r in rows]


@router.get("/runs/{run_id}")
def get_run(run_id: str, db: Database = Depends(get_db), user: dict = Depends(get_current_user)):
    oid = parse_id(run_id)
    run = db.generation_runs.find_one({"_id": oid, "user_id": user["_id"]}) if oid else None
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return _jsonable(run)
