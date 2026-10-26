import difflib
import json
import math
import re
from concurrent.futures import ThreadPoolExecutor

from groq import Groq
from pydantic import BaseModel, Field

from app import trace
from app.config import GROQ_API_KEY
from app.trace import traced_create

# Groq production model (listed at console.groq.com/docs/models)
MODEL = "openai/gpt-oss-120b"

# Long notes are split into chunks of about CHUNK_CHARS and processed in parallel
MAX_NOTES_CHARS = 200_000
CHUNK_CHARS = 6_000
MAX_CHUNKS = 20

SYSTEM_PROMPT = """You turn the user's study notes into flashcards.

Rules:
- Use ONLY information stated in the notes. Never add outside facts, examples or context.
- Every card must have a "source" that is ONE sentence copied EXACTLY, character for character, from the notes.
- The "question" and "answer" must be fully answerable from that source sentence.
- Even short notes should give cards: make one card per distinct fact, definition or idea.
- Only return an empty list if the notes contain no facts at all.

Respond with a JSON object only, in this shape:
{"cards": [{"question": "...", "answer": "...", "source": "..."}]}"""


class NotesRequest(BaseModel):
    notes: str = Field(min_length=20, max_length=MAX_NOTES_CHARS)
    max_cards: int = Field(default=10, ge=1, le=30)


class Flashcard(BaseModel):
    question: str
    answer: str
    source: str


class FlashcardsResponse(BaseModel):
    cards: list[Flashcard]
    dropped: int  # cards removed because their source was not found in the notes


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def _split_chunks(notes: str, size: int = CHUNK_CHARS) -> list[str]:
    chunks, current = [], ""
    for sentence in _split_sentences(notes):
        if current and len(current) + len(sentence) + 1 > size:
            chunks.append(current)
            current = ""
        current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current)
    return chunks or [notes]


def _loose(text: str) -> str:
    # Ignore case, punctuation and quote/dash style so harmless differences don't discard a card
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _snap_source(source: str, sentences: list[str], loose_notes: str) -> str | None:
    """Return a sentence that really is in the notes, or None if the model's quote can't be matched."""
    loose_source = _loose(source)
    if not loose_source:
        return None
    for sentence in sentences:
        if loose_source == _loose(sentence):
            trace.count("source_match_exact")
            return sentence
    if loose_source in loose_notes:
        for sentence in sentences:
            if loose_source in _loose(sentence):
                trace.count("source_match_substring")
                return sentence
    best, best_ratio = None, 0.0
    for sentence in sentences:
        ratio = difflib.SequenceMatcher(None, loose_source, _loose(sentence)).ratio()
        if ratio > best_ratio:
            best, best_ratio = sentence, ratio
    trace.count("source_match_fuzzy" if best_ratio >= 0.8 else "source_rejected")
    return best if best_ratio >= 0.8 else None


def _ask_model(notes: str, max_cards: int) -> list[dict]:
    client = Groq(api_key=GROQ_API_KEY, max_retries=6)
    completion = traced_create(
        client,
        "cards:generate",
        model=MODEL,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Create at most {max_cards} flashcards from these notes.\n\nNOTES:\n{notes}",
            },
        ],
    )
    raw = json.loads(completion.choices[0].message.content)
    return [c for c in raw.get("cards", []) if isinstance(c, dict)]


def _cards_for_chunk(chunk: str, max_cards: int) -> tuple[list[Flashcard], int]:
    sentences = _split_sentences(chunk)
    loose_chunk = _loose(chunk)
    candidates: list[dict] = []
    cards: list[Flashcard] = []
    for attempt in range(2):  # one retry if nothing usable came back
        candidates = _ask_model(chunk, max_cards)
        cards = []
        for item in candidates:
            try:
                card = Flashcard(**item)
            except Exception:
                continue
            source = _snap_source(card.source, sentences, loose_chunk)
            if source:
                cards.append(Flashcard(question=card.question, answer=card.answer, source=source))
        if cards:
            break
    trace.chunk_result(
        attempts=attempt + 1,
        sentence_units=len(sentences),
        candidates=len(candidates),
        kept=len(cards),
        dropped=len(candidates) - len(cards),
    )
    return cards, len(candidates) - len(cards)


def generate_flashcards(notes: str, max_cards: int) -> FlashcardsResponse:
    all_chunks = _split_chunks(notes)
    chunks = all_chunks[:MAX_CHUNKS]
    per_chunk = max(2, math.ceil(max_cards / len(chunks)))
    trace.meta(
        chunk_chars=CHUNK_CHARS,
        max_chunks=MAX_CHUNKS,
        chunks_total=len(all_chunks),
        chunks_used=len(chunks),
        chars_not_used=sum(len(c) for c in all_chunks[MAX_CHUNKS:]),
        cards_requested=max_cards,
        cards_per_chunk_target=per_chunk,
    )

    def safe(index: int, chunk: str):
        # A chunk that still fails after retries is skipped so the other chunks' cards aren't lost
        with trace.chunk_scope(index, chars=len(chunk)):
            try:
                return _cards_for_chunk(chunk, per_chunk), None
            except Exception as e:
                trace.chunk_result(error=type(e).__name__)
                return ([], 0), e

    with ThreadPoolExecutor(max_workers=min(2, len(chunks))) as pool:
        outcomes = trace.map_in_context(pool, safe, list(enumerate(chunks)))
    if all(err is not None for _, err in outcomes):
        raise outcomes[0][1]
    results = [r for r, _ in outcomes]

    cards: list[Flashcard] = []
    seen: set[str] = set()
    dropped = 0
    for chunk_cards, chunk_dropped in results:
        dropped += chunk_dropped
        for card in chunk_cards:
            key = _loose(card.question)
            if key not in seen:
                seen.add(key)
                cards.append(card)

    trace.meta(
        cards_before_dedupe=sum(len(c) for c, _ in results),
        cards_after_dedupe=len(cards),
        cards_returned=len(cards[:max_cards]),
        cards_dropped_no_source=dropped,
    )
    return FlashcardsResponse(cards=cards[:max_cards], dropped=dropped)
