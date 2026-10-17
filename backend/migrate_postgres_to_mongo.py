"""One-off: copies users, notes and cards from the old PostgreSQL database into MongoDB.

Needs psycopg2 only for this script:  pip install psycopg2-binary
Run from backend/:  python migrate_postgres_to_mongo.py postgresql://postgres:password@localhost:5432/study_guide

Safe to re-run only against an empty MongoDB database (it refuses otherwise).
Old integer ids are replaced by new ObjectIds; the relationships between rows are preserved.
Note: existing login tokens stop working, so everyone signs in again once.
"""
import sys

import psycopg2
import psycopg2.extras

from app.database import db, init_indexes


def main(pg_url: str):
    if db.users.estimated_document_count() or db.notes.estimated_document_count() or db.cards.estimated_document_count():
        sys.exit("MongoDB database is not empty; refusing to migrate into it.")

    pg = psycopg2.connect(pg_url)
    cur = pg.cursor(cursor_factory=psycopg2.extras.DictCursor)
    init_indexes()

    user_ids = {}  # old int id -> new ObjectId
    cur.execute("SELECT * FROM users ORDER BY id")
    for row in cur.fetchall():
        res = db.users.insert_one(
            {"email": row["email"], "password_hash": row["password_hash"], "created_at": row["created_at"]}
        )
        user_ids[row["id"]] = res.inserted_id

    note_ids, note_owner = {}, {}
    cur.execute("SELECT * FROM notes ORDER BY id")
    skipped_notes = 0
    for row in cur.fetchall():
        if row["user_id"] is None:
            # Pre-accounts notes have no owner, and nothing could ever show them to anyone
            skipped_notes += 1
            continue
        res = db.notes.insert_one(
            {"user_id": user_ids[row["user_id"]], "text": row["text"], "created_at": row["created_at"]}
        )
        note_ids[row["id"]] = res.inserted_id
        note_owner[row["id"]] = user_ids[row["user_id"]]

    cards = []
    cur.execute("SELECT * FROM cards ORDER BY id")
    for row in cur.fetchall():
        if row["note_id"] not in note_ids:
            continue
        cards.append(
            {
                "note_id": note_ids[row["note_id"]],
                "user_id": note_owner[row["note_id"]],
                "question": row["question"],
                "answer": row["answer"],
                "source": row["source"],
                "status": row["status"],
                "created_at": row["created_at"],
                "check_status": row["check_status"],
                "check_reason": row["check_reason"],
                "ease_factor": row["ease_factor"],
                "interval_days": row["interval_days"],
                "repetitions": row["repetitions"],
                "due_date": row["due_date"].isoformat() if row["due_date"] else None,
            }
        )
    if cards:
        db.cards.insert_many(cards)

    print(f"Migrated {len(user_ids)} users, {len(note_ids)} notes, {len(cards)} cards.")
    if skipped_notes:
        print(f"Skipped {skipped_notes} notes that had no owner (and their cards).")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
