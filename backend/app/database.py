from pymongo import ASCENDING, MongoClient
from pymongo.database import Database

from app.config import MONGODB_DB, MONGODB_URL

# tz_aware so stored datetimes come back as UTC-aware, like the old timezone-aware columns.
# MongoClient connects lazily and pools connections itself.
client = MongoClient(MONGODB_URL, tz_aware=True, serverSelectionTimeoutMS=5000)
db = client[MONGODB_DB]


def get_db() -> Database:
    # The client is shared and thread-safe, so there is nothing to open or close per request
    return db


def init_indexes():
    # Safe to run every startup: creating an index that already exists is a no-op
    db.users.create_index("email", unique=True)
    db.notes.create_index("user_id")
    db.cards.create_index("note_id")
    db.cards.create_index([("user_id", ASCENDING), ("status", ASCENDING)])
    db.cards.create_index([("user_id", ASCENDING), ("status", ASCENDING), ("due_date", ASCENDING)])
    db.cards.create_index([("user_id", ASCENDING), ("check_status", ASCENDING)])
