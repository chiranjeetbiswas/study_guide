from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pymongo.database import Database

from app.auth import get_current_user, router as auth_router
from app.cards import router as cards_router
from app.chunks_api import router as chunks_router
from app.config import FRONTEND_ORIGINS, GROQ_API_KEY
from app.database import get_db, init_indexes
from app.debug import router as debug_router
from app.generate import router as generate_router
from app.quiz import router as quiz_router
from app.studyset import router as studyset_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Collections are created on first write; indexes (incl. unique email) are created here
    init_indexes()
    yield


app = FastAPI(title="AI Study Guide", lifespan=lifespan)

# Lets the Next.js frontend (localhost:3001, or FRONTEND_ORIGIN when deployed) call this backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(generate_router)
app.include_router(cards_router)
app.include_router(quiz_router)
app.include_router(studyset_router)
app.include_router(chunks_router)
app.include_router(debug_router)


@app.get("/")
def root():
    return {"message": "AI Study Guide API is running"}


class CheckStats(BaseModel):
    checked: int
    supported: int
    flagged: int
    flagged_rate: float  # 0.0 - 1.0, 0 when nothing has been checked


@app.get("/stats/checks", response_model=CheckStats)
def check_stats(db: Database = Depends(get_db), user: dict = Depends(get_current_user)):
    """Your hallucination-check results across every checked card (including rejected ones)."""
    rows = {
        row["_id"]: row["n"]
        for row in db.cards.aggregate(
            [
                {"$match": {"user_id": user["_id"], "check_status": {"$ne": None}}},
                {"$group": {"_id": "$check_status", "n": {"$sum": 1}}},
            ]
        )
    }
    supported, flagged = rows.get("supported", 0), rows.get("flagged", 0)
    checked = supported + flagged
    return CheckStats(checked=checked, supported=supported, flagged=flagged, flagged_rate=flagged / checked if checked else 0.0)


@app.get("/health")
def health():
    # Only reports whether the key exists - never return the key itself
    return {"status": "ok", "groq_key_loaded": bool(GROQ_API_KEY) and not GROQ_API_KEY.startswith("paste-")}
