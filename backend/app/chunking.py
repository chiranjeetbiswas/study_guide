"""Structured chunking pipeline (RAG Phase 1b).

    pages  ->  clean  ->  detect structure  ->  chunk  ->  add overlap  ->  attach metadata

Every stage is a plain function, deterministic (same input and settings give the same chunks) and has no
AI and no database in it. Persistence lives in chunk_store.py.

The old chunker (flashcards._split_chunks) is untouched. It still feeds flashcard and revision generation.
This one produces the chunks that are stored for later phases (embeddings, retrieval).

Sizes are in CHARACTERS, like the rest of the app. Rule of thumb for English: 1 token is about 4 characters,
so 1,200 characters is about 300 tokens.
"""

import math
import os
import re
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()

CHUNKER_VERSION = "structured-v1"

# The two numbers to experiment with. Override per run (rebuild API, CLI flags) or globally with env vars.
#
# CHUNK_SIZE: maximum characters of NEW text in a chunk. One chunk should hold about one idea: big enough to
#   carry context, small enough that a search hit points at the right place. 1,200 chars is a few sentences up
#   to two short paragraphs, which is also well under the input limit of common embedding models.
#   The one exception: a chunk may go over by the length of its headings when that is the only way to avoid
#   a chunk that contains nothing but a heading (only happens at small sizes).
# CHUNK_OVERLAP: characters repeated from the end of the previous chunk at the start of the next one.
#   A chunk's `content` can therefore be up to CHUNK_SIZE + CHUNK_OVERLAP characters.
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1200"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "200"))

MIN_CHUNK_SIZE = 200
# A top-level heading starts a new chunk if the current chunk already holds at least this share of CHUNK_SIZE
SECTION_BREAK_FRACTION = 0.3
OVERLAP_SEP = "\n\n"  # between the overlap and the new text inside `content`

_TERMINAL = re.compile(r"[.!?][\"')\]]*$")
_LIST_ITEM = re.compile(r"^([-*•]|\d+[.)])\s+")
_NUMBERED = re.compile(r"^(\d+(?:\.\d+)*)[.)]?\s+\S")
_CHAPTER = re.compile(r"^(chapter|unit|part|module|lesson)\s+[\dIVXLC]+\b", re.IGNORECASE)
_SENTENCE_END = re.compile(r"([.!?][\"')\]]*)\s+(?=[\"'(\[]?[A-Z0-9])")
_ABBREVIATIONS = {
    "dr", "mr", "mrs", "ms", "prof", "sr", "jr", "st", "vs", "etc", "fig", "figs", "eq", "no", "nos",
    "approx", "e.g", "i.e", "cf", "al", "vol", "pp", "sec", "ch", "ca", "inc", "ltd", "co",
}


# ---------- data ----------


@dataclass
class Page:
    number: int | None  # None when the source has no pages (pasted text, .txt)
    text: str


@dataclass
class Block:
    """One structural unit of the document: a heading, a paragraph, or a list item."""

    kind: str  # "heading" | "paragraph" | "list_item"
    text: str
    page_start: int | None
    page_end: int | None
    level: int | None = None  # headings only: 0 = chapter/title, 1 = section, 2+ = sub-section
    heading: str | None = None  # the heading in effect for this block (a heading's own text for itself)
    section: str | None = None  # the top-level (section) heading in effect


@dataclass
class Piece:
    """What actually gets packed into chunks: a whole block, or one slice of a block too long for one chunk."""

    block_index: int
    kind: str
    text: str
    page_start: int | None
    page_end: int | None
    level: int | None
    heading: str | None
    section: str | None
    split: str | None = None  # None = whole block; "sentence" or "word" = this is a slice of a longer block
    last_slice: bool = True


@dataclass
class Chunk:
    index: int
    content: str  # what will be embedded: [overlap][OVERLAP_SEP]new text
    overlap_chars: int  # length of the overlap prefix (0 for the first chunk or when overlap is off)
    page_number: int | None  # first page the new text is on
    page_end: int | None  # last page, only when different from page_number
    heading: str | None
    section: str | None
    headings: list[str]  # headings that appear inside the new text
    end_kind: str  # how the new text ends: "block" (clean) | "sentence" (inside a paragraph) | "word" (inside a sentence)
    block_kinds: list[str] = field(default_factory=list)

    @property
    def own_text(self) -> str:
        return self.content[self.overlap_chars + len(OVERLAP_SEP) :] if self.overlap_chars else self.content


@dataclass
class ChunkingResult:
    chunks: list[Chunk]
    blocks: list[Block]
    noise_removed: list[dict]  # repeated page headers/footers dropped during cleaning
    pages: int
    size: int
    overlap: int


# ---------- stage 1: clean ----------


def _page_lines(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    return [re.sub(r"[ \t ​]+", " ", line).strip() for line in text.split("\n")]


def _edge_positions(lines: list[str]) -> set[int]:
    """Indexes of the first two and last two non-blank lines (where running headers and footers live)."""
    filled = [i for i, line in enumerate(lines) if line]
    return set(filled[:2] + filled[-2:])


def _edge_key(line: str) -> str:
    return re.sub(r"\d+", "#", line.lower())  # "Page 2" and "Page 3" count as the same line


def remove_repeated_edges(pages: list[list[str]]) -> tuple[list[list[str]], list[dict]]:
    """Drops short lines that repeat at the top or bottom of most pages (page numbers, running headers,
    footers). They are layout, not content, and would otherwise end up in the middle of sentences."""
    if len(pages) < 2:
        return pages, []
    counts: dict[str, int] = {}
    for lines in pages:
        keys = {_edge_key(lines[i]) for i in _edge_positions(lines) if len(lines[i]) <= 80}
        for key in keys:
            counts[key] = counts.get(key, 0) + 1
    needed = max(2, math.ceil(0.6 * len(pages)))
    noisy = {key for key, n in counts.items() if n >= needed}

    cleaned, removed = [], {}
    for lines in pages:
        edges = _edge_positions(lines)
        kept = []
        for i, line in enumerate(lines):
            if i in edges and line and len(line) <= 80 and _edge_key(line) in noisy:
                entry = removed.setdefault(_edge_key(line), {"example": line, "times": 0})
                entry["times"] += 1
                continue
            kept.append(line)
        cleaned.append(kept)
    return cleaned, list(removed.values())


# ---------- stage 2: detect structure ----------


def _heading_level(line: str, starts_block: bool, next_line: str) -> int | None:
    """Heading level, or None if the line is not a heading. Deterministic rules, so you can see exactly why
    something was or was not called a heading:
      - "Chapter 6: ..." / "Unit 2 ..."          -> level 0
      - "1. Title", "2.1 Title" (short, no ?)    -> level = number of dotted parts
      - ALL CAPS short line                      -> level 1
      - short Title-like line that starts a block and is followed by a capitalised line -> level 1
    A line that ends like a sentence is never a heading."""
    words = len(line.split())
    if len(line) > 80 or not any(ch.isalpha() for ch in line) or line[0] in "-*•":
        return None
    if _TERMINAL.search(line) or line.endswith((",", ";")):
        return None
    if _CHAPTER.match(line):
        return 0
    numbered = _NUMBERED.match(line)
    if numbered and words <= 10 and "?" not in line and "]" not in line:
        return numbered.group(1).count(".") + 1
    letters = [ch for ch in line if ch.isalpha()]
    if len(letters) >= 3 and all(ch.isupper() for ch in letters) and words <= 10:
        return 1
    if starts_block and words <= 10 and line[0].isupper() and next_line and (next_line[0].isupper() or next_line[0].isdigit()):
        return 1
    return None


def _join_lines(lines: list[str]) -> str:
    """Joins hard-wrapped lines into one paragraph, re-joining words split with a hyphen at a line end."""
    text = lines[0]
    for line in lines[1:]:
        if text.endswith("-") and len(text) > 1 and text[-2].isalpha() and line[:1].islower():
            text = text[:-1] + line
        else:
            text += " " + line
    return text


def _blocks_from_page(lines: list[str], page: int | None) -> list[Block]:
    lengths = sorted(len(line) for line in lines if line)
    width = lengths[int(0.9 * (len(lengths) - 1))] if lengths else 0  # typical full-line width on this page
    blocks: list[Block] = []
    current: list | None = None  # [kind, [lines]] for the paragraph or list item being built

    def flush():
        nonlocal current
        if current:
            blocks.append(Block(current[0], _join_lines(current[1]), page, page))
        current = None

    prev, prev_len = "", 0
    for i, line in enumerate(lines):
        if not line:
            flush()
            prev, prev_len = "", 0
            continue
        next_line = next((ln for ln in lines[i + 1 :] if ln), "")
        starts_block = current is None or bool(_TERMINAL.search(prev))
        level = _heading_level(line, starts_block, next_line)
        if level is not None:
            flush()
            blocks.append(Block("heading", line, page, page, level=level))
        elif _LIST_ITEM.match(line):
            flush()
            current = ["list_item", [line]]
        elif current is None:
            current = ["paragraph", [line]]
        else:
            # A hard-wrapped paragraph breaks where a line ends a sentence but stops short of the margin
            if _TERMINAL.search(prev) and prev_len < 0.85 * width and line[0].isupper():
                flush()
                current = ["paragraph", [line]]
            else:
                current[1].append(line)
        prev, prev_len = line, len(line)
    flush()
    return blocks


def detect_blocks(pages: list[Page], page_lines: list[list[str]]) -> list[Block]:
    blocks: list[Block] = []
    for page, lines in zip(pages, page_lines):
        blocks.extend(_blocks_from_page(lines, page.number))

    # A paragraph that runs over a page break is one paragraph, not two
    merged: list[Block] = []
    for block in blocks:
        prev = merged[-1] if merged else None
        if (
            prev
            and prev.kind in ("paragraph", "list_item")
            and block.kind == "paragraph"
            and not _TERMINAL.search(prev.text)
            and block.text[:1].islower()
            and prev.page_end is not None
            and block.page_start == prev.page_end + 1
        ):
            prev.text = _join_lines([prev.text, block.text])
            prev.page_end = block.page_end
        else:
            merged.append(block)

    # Which heading / section is each block under?
    title = section = heading = None
    for block in merged:
        if block.kind == "heading":
            if block.level == 0:
                title, section, heading = block.text, None, block.text
            elif block.level == 1:
                section, heading = block.text, block.text
            else:
                heading = block.text
        block.heading = heading
        block.section = section or (title if block.kind == "heading" and block.level == 0 else None)
    return merged


# ---------- sentences (used to split long paragraphs and to build overlap) ----------


def _is_abbreviation(fragment: str) -> bool:
    words = fragment.rstrip(".\"')]").split()
    if not words:
        return False
    word = words[-1].lower()
    return word in _ABBREVIATIONS or (len(word) == 1 and word.isalpha())  # "Dr.", "Fig.", "e.g.", initials


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    """(start, end) offsets of each sentence. Every newline also ends a sentence, and abbreviations
    ("Dr. Smith", "Fig. 2", "e.g. a mint") do not."""
    spans = []
    pos = 0
    for line in re.split(r"(\n+)", text):
        if line.strip() and not line.startswith("\n"):
            start = 0
            for match in _SENTENCE_END.finditer(line):
                end = match.end(1)
                if match.group(1).startswith(".") and _is_abbreviation(line[start:end]):
                    continue
                spans.append((pos + start, pos + end))
                start = match.end()
            if line[start:].strip():
                spans.append((pos + start, pos + len(line.rstrip())))
        pos += len(line)
    return spans


def split_sentences(text: str) -> list[str]:
    return [text[start:end].strip() for start, end in _sentence_spans(text) if text[start:end].strip()]


def _split_words(text: str, size: int) -> list[str]:
    parts, current = [], ""
    for word in text.split():
        if current and len(current) + 1 + len(word) > size:
            parts.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        parts.append(current)
    return parts


# ---------- stage 3: chunk ----------


def _expand(blocks: list[Block], size: int) -> list[Piece]:
    pieces = []
    for index, block in enumerate(blocks):
        base = dict(
            block_index=index, kind=block.kind, page_start=block.page_start, page_end=block.page_end,
            level=block.level, heading=block.heading, section=block.section,
        )
        if block.kind == "heading" or len(block.text) <= size:
            pieces.append(Piece(text=block.text, **base))
            continue
        # A block longer than one chunk is split at sentence boundaries (words only as a last resort)
        parts: list[tuple[str, str]] = []
        current = ""
        for sentence in split_sentences(block.text):
            if len(sentence) > size:
                if current:
                    parts.append((current, "sentence"))
                    current = ""
                parts.extend((w, "word") for w in _split_words(sentence, size))
            elif current and len(current) + 1 + len(sentence) > size:
                parts.append((current, "sentence"))
                current = sentence
            else:
                current = f"{current} {sentence}".strip()
        if current:
            parts.append((current, "sentence"))
        for n, (text, how) in enumerate(parts):
            pieces.append(Piece(text=text, split=how, last_slice=n == len(parts) - 1, **base))
    return pieces


def _separator(prev: Piece, nxt: Piece) -> str:
    if prev.block_index == nxt.block_index:
        return " "
    if prev.kind == "heading" or (prev.kind == "list_item" and nxt.kind == "list_item"):
        return "\n"
    return "\n\n"


def _joined(pieces: list[Piece]) -> str:
    text = ""
    for i, piece in enumerate(pieces):
        text += (_separator(pieces[i - 1], piece) if i else "") + piece.text
    return text


def _group(pieces: list[Piece], size: int) -> list[list[Piece]]:
    """Packs pieces into groups of at most `size` characters, in document order."""
    section_break_min = size * SECTION_BREAK_FRACTION
    groups: list[list[Piece]] = []
    current: list[Piece] = []
    length = 0
    for piece in pieces:
        if current:
            added = len(_separator(current[-1], piece)) + len(piece.text)
            starts_section = piece.kind == "heading" and piece.level is not None and piece.level <= 1
            if starts_section and length >= section_break_min:
                groups.append(current)  # a new section starts a new chunk
                current, length = [], 0
            elif length + added > size and all(p.kind == "heading" for p in current):
                pass  # only headings so far: keep them with the text that follows, even if that goes a little over `size`
            elif length + added > size:
                carry: list[Piece] = []
                while len(current) > 1 and current[-1].kind == "heading":
                    carry.insert(0, current.pop())  # never leave a heading stranded at the end of a chunk
                groups.append(current)
                current = carry
                length = len(_joined(current))
        length += (len(_separator(current[-1], piece)) if current else 0) + len(piece.text)
        current.append(piece)
    if current:
        groups.append(current)
    return groups


# ---------- stage 4: overlap ----------


def _overlap_tail(previous_text: str, overlap: int) -> str:
    """The end of the previous chunk's new text, starting at a sentence boundary, at most `overlap` characters.
    It is a real slice of that text, so line breaks (lists, headings) are kept. If even the last sentence is
    longer than `overlap`, it is the trailing words that fit."""
    if overlap <= 0 or not previous_text:
        return ""
    previous_text = previous_text.rstrip()
    for start, _ in _sentence_spans(previous_text):
        if len(previous_text) - start <= overlap:
            return previous_text[start:]
    tail = previous_text[-overlap:]
    cut = re.search(r"\s", tail)
    return tail[cut.end() :].strip() if cut else tail.strip()


# ---------- stage 5: metadata, and the whole pipeline ----------


def build_chunks(blocks: list[Block], size: int, overlap: int) -> list[Chunk]:
    groups = _group(_expand(blocks, size), size)
    chunks: list[Chunk] = []
    previous_text = ""
    for index, group in enumerate(groups):
        own = _joined(group)
        tail = _overlap_tail(previous_text, overlap) if index else ""
        first, last = group[0], group[-1]
        pages_start = [p.page_start for p in group if p.page_start is not None]
        pages_end = [p.page_end for p in group if p.page_end is not None]
        page_number = min(pages_start) if pages_start else None
        page_end = max(pages_end) if pages_end else None
        chunks.append(
            Chunk(
                index=index,
                content=f"{tail}{OVERLAP_SEP}{own}" if tail else own,
                overlap_chars=len(tail),
                page_number=page_number,
                page_end=page_end if page_end != page_number else None,
                heading=first.heading,
                section=first.section,
                headings=[p.text for p in group if p.kind == "heading"],
                end_kind=last.split if (last.split and not last.last_slice) else "block",
                block_kinds=[p.kind for p in group],
            )
        )
        previous_text = own
    return chunks


def pages_from_text(text: str) -> list[Page]:
    return [Page(None, text)]


def chunk_document(pages: list[Page], *, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> ChunkingResult:
    if size < MIN_CHUNK_SIZE:
        raise ValueError(f"chunk size must be at least {MIN_CHUNK_SIZE} characters")
    if not 0 <= overlap <= size // 2:
        raise ValueError(f"chunk overlap must be between 0 and half the chunk size ({size // 2})")
    page_lines, noise = remove_repeated_edges([_page_lines(p.text) for p in pages])
    blocks = detect_blocks(pages, page_lines)
    return ChunkingResult(
        chunks=build_chunks(blocks, size, overlap),
        blocks=blocks,
        noise_removed=noise,
        pages=len(pages),
        size=size,
        overlap=overlap,
    )
