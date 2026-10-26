"""Chunk inspector (RAG Phase 1a).

Shows what the CURRENT chunker does to a document. It calls the production `_split_chunks()` and
`_split_sentences()` unchanged and only measures their output: where each chunk starts and ends in the
original text, what structure (headings, paragraphs, line breaks) was flattened, and where it cut.

Nothing here feeds back into generation.
"""

import io
import re
from statistics import mean

from pypdf import PdfReader

from app.extract import extract_text
from app.flashcards import CHUNK_CHARS, MAX_CHUNKS, MAX_NOTES_CHARS, _split_chunks, _split_sentences
from app.studyset import DIRECT_CONTEXT_CHARS, MAX_REVISION_CHUNKS, REVISION_CHUNK_CHARS

PROFILES = {
    "flashcards": {"size": CHUNK_CHARS, "max_chunks": MAX_CHUNKS, "used_by": "flashcard generation, one Groq call per chunk"},
    "revision": {
        "size": REVISION_CHUNK_CHARS,
        "max_chunks": MAX_REVISION_CHUNKS,
        "used_by": "revision notes, one Groq call per chunk",
    },
}

_TERMINAL = re.compile(r"[.!?][\"')\]]*$")
_NUMBERED = re.compile(r"^(\d+(\.\d+)*[.)]?|[IVXLC]+[.)]|[A-Za-z][.)])\s+\S")
_BLANK_LINE = re.compile(r"\n[ \t]*\n")


# ---------- reading a file, keeping page information when the format has it ----------


def extract_with_pages(filename: str, data: bytes) -> tuple[str, list[tuple[int, int, int]] | None]:
    """Same text the app gets from extract_text(...).strip(), plus (page, start, end) offsets for PDFs.

    The app itself throws page numbers away (extract.py joins the pages) and stores only the text, so this
    is the only place page information exists. Offsets are recomputed here for inspection only."""
    text = extract_text(filename, data).strip()
    if not filename.lower().endswith(".pdf"):
        return text, None
    try:
        pages = [(page.extract_text() or "") for page in PdfReader(io.BytesIO(data)).pages]
    except Exception:
        return text, None
    raw = "\n".join(pages)
    lead = len(raw) - len(raw.lstrip())
    spans, pos = [], 0
    for number, page_text in enumerate(pages, start=1):
        spans.append((number, max(pos - lead, 0), max(pos + len(page_text) - lead, 0)))
        pos += len(page_text) + 1
    if raw.strip() != text:  # extraction differs from what the app uses: don't claim page numbers
        return text, None
    return text, spans


# ---------- helpers ----------


def _normalize_with_map(text: str) -> tuple[str, list[int]]:
    """Collapses whitespace runs to one space (like the chunker's joins do) and remembers, for every
    character of the result, its offset in the original text."""
    out, offsets, prev_space = [], [], False
    for i, ch in enumerate(text):
        if ch.isspace():
            if prev_space:
                continue
            out.append(" ")
            prev_space = True
        else:
            out.append(ch)
            prev_space = False
        offsets.append(i)
    return "".join(out), offsets


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _nonspace(text: str) -> int:
    return sum(1 for ch in text if not ch.isspace())


def find_headings(text: str) -> list[dict]:
    """Heuristic only: a short line that doesn't end like a sentence and is numbered, ALL CAPS, or starts a block."""
    lines, pos = [], 0
    for raw in text.split("\n"):
        lines.append((pos, pos + len(raw), raw))
        pos += len(raw) + 1

    headings = []
    for i, (start, end, raw) in enumerate(lines):
        line = raw.strip()
        if not line or len(line) > 70 or not any(ch.isalpha() for ch in line):
            continue
        if line[0] in "-*•" or _TERMINAL.search(line) or line.endswith((",", ";")):
            continue
        if not (line[0].isupper() or line[0].isdigit()):
            continue
        prev = lines[i - 1][2].strip() if i > 0 else ""
        nxt = lines[i + 1][2].strip() if i + 1 < len(lines) else ""
        letters = [c for c in line if c.isalpha()]
        all_caps = len(letters) >= 3 and all(c.isupper() for c in letters)
        starts_block = (not prev) or bool(_TERMINAL.search(prev))
        title_like = starts_block and bool(nxt) and (nxt[0].isupper() or nxt[0].isdigit())
        if _NUMBERED.match(line) or all_caps or title_like:
            headings.append({"text": line, "start": start + raw.index(line[0]), "end": end, "line": i + 1})
    return headings


def _unit_stats(text: str, preview_chars: int) -> dict:
    units = _split_sentences(text)
    lengths = [len(u) for u in units]
    short = [(i, u) for i, u in enumerate(units) if len(u) < 25]
    unterminated = [u for u in units if not _TERMINAL.search(u)]
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    wrapped = [ln for ln in lines if len(ln) >= 60 and not _TERMINAL.search(ln)]
    return {
        "what": "pieces produced by _split_sentences(): split after . ! ? plus whitespace, AND at every newline",
        "count": len(units),
        "chars_min": min(lengths, default=0),
        "chars_avg": round(mean(lengths)) if lengths else 0,
        "chars_max": max(lengths, default=0),
        "short_under_25_chars": len(short),
        "short_examples": [{"unit": i, "text": u[:preview_chars]} for i, u in short[:8]],
        "not_ending_like_a_sentence": len(unterminated),
        "lines_total": len(lines),
        "long_lines_without_end_punctuation": len(wrapped),
        "looks_like_hard_wrapped_text": len(lines) > 5 and len(wrapped) / len(lines) > 0.3,
    }


def _pages_for(start: int, end: int, spans) -> str | None:
    if not spans:
        return None
    hit = [n for n, s, e in spans if s < end and e > start]
    if not hit:
        return None
    return str(hit[0]) if hit[0] == hit[-1] else f"{hit[0]}-{hit[-1]}"


# ---------- one profile (= one chunk size) ----------


def _inspect_profile(text: str, name: str, spec: dict, headings: list[dict], spans, preview_chars: int) -> dict:
    size, max_chunks = spec["size"], spec["max_chunks"]
    chunks = _split_chunks(text, size)  # the production function, called exactly as the app calls it
    norm, offsets = _normalize_with_map(text)

    rows, cursor = [], 0
    for i, chunk in enumerate(chunks):
        norm_chunk = _collapse(chunk)
        pos = norm.find(norm_chunk, cursor)
        located = pos != -1
        if not located:  # should not happen; keep going with a best effort
            pos = cursor
        start = offsets[pos] if offsets else 0
        last = min(pos + len(norm_chunk) - 1, len(offsets) - 1)
        end = offsets[last] + 1 if offsets else 0
        cursor = pos + len(norm_chunk)
        rows.append({"i": i, "chunk": chunk, "start": start, "end": end, "located": located})

    out_chunks, boundaries = [], {"paragraph_break": 0, "line_break": 0, "same_line": 0}
    glued_total = orphan_headings = mid_sentence_cuts = flattened_nl = flattened_blank = 0

    for n, row in enumerate(rows):
        chunk, start, end = row["chunk"], row["start"], row["end"]
        span = text[start:end]
        in_span = [h for h in headings if h["start"] >= start and h["end"] <= end]

        # what separates this chunk from the next one in the ORIGINAL text
        break_after = None
        if n + 1 < len(rows):
            gap = text[end : rows[n + 1]["start"]]
            if _BLANK_LINE.search(gap):
                break_after = "paragraph_break"
            elif "\n" in gap:
                break_after = "line_break"
            else:
                break_after = "same_line"
            boundaries[break_after] += 1

        ends_mid = not _TERMINAL.search(chunk.rstrip())
        starts_mid = chunk[:1].islower()
        if n + 1 < len(rows) and ends_mid:
            mid_sentence_cuts += 1

        last_line = span.rstrip().split("\n")[-1].strip()
        heading_is_last_line = n + 1 < len(rows) and any(h["text"] == last_line for h in in_span)
        orphan_headings += heading_is_last_line

        # Headings that the card-source matcher sees glued to the start of a sentence:
        # _cards_for_chunk re-splits the (already flattened) chunk, so a heading line with no full stop
        # is joined to the sentence after it.
        units = _split_sentences(chunk)
        glued = []
        for h in in_span:
            h_norm = _collapse(h["text"])
            for u in units:
                if u.startswith(h_norm + " ") and len(u) > len(h_norm) + 1:
                    glued.append({"heading": h["text"], "unit_starts_with": u[: preview_chars]})
                    break
        glued_total += len(glued)

        nl, blank = span.count("\n"), len(_BLANK_LINE.findall(span))
        flattened_nl += nl
        flattened_blank += blank

        out_chunks.append(
            {
                "index": n,
                "used": n < max_chunks,
                "chars": len(chunk),
                "over_size_limit": len(chunk) > size,
                "original_start": start,
                "original_end": end,
                "original_lines": f"{text.count(chr(10), 0, start) + 1}-{text.count(chr(10), 0, end) + 1}",
                "pages": _pages_for(start, end, spans),
                "located_in_original": row["located"],
                "break_after": break_after,
                "starts_mid_sentence": starts_mid,
                "ends_mid_sentence": ends_mid,
                "preview_start": chunk[:preview_chars],
                "preview_end": chunk[-preview_chars:],
                "original_preview_start": span[:preview_chars],
                "original_preview_end": span[-preview_chars:],
                "structure": {
                    "headings_in_span": [h["text"] for h in in_span],
                    "heading_is_last_line_of_chunk": heading_is_last_line,
                    "newlines_turned_into_spaces": nl,
                    "blank_lines_turned_into_spaces": blank,
                    "paragraph_blocks_in_span": len([b for b in _BLANK_LINE.split(span) if b.strip()]),
                    "sentence_units_in_chunk": len(units),
                    "headings_glued_into_a_sentence_unit": glued[:3],
                },
            }
        )

    sizes = [c["chars"] for c in out_chunks]
    used = [c for c in out_chunks if c["used"]]
    return {
        "chunk_chars": size,
        "overlap_chars": 0,
        "max_chunks_used_per_generation": max_chunks,
        "used_by": spec["used_by"],
        "chunk_count": len(out_chunks),
        "chunks_used": len(used),
        "chars_in_unused_chunks": sum(c["chars"] for c in out_chunks if not c["used"]),
        "chunk_chars_min": min(sizes, default=0),
        "chunk_chars_avg": round(mean(sizes)) if sizes else 0,
        "chunk_chars_max": max(sizes, default=0),
        "summary": {
            "boundaries_between_chunks": boundaries,
            "cuts_that_end_mid_sentence": mid_sentence_cuts,
            "headings_found": len(headings),
            "headings_left_as_last_line_of_a_chunk": orphan_headings,
            "headings_glued_into_a_sentence_unit": glued_total,
            "newlines_turned_into_spaces": flattened_nl,
            "blank_lines_turned_into_spaces": flattened_blank,
            # every non-space character of the document should appear in exactly one chunk
            "non_space_chars_lost": _nonspace(text) - sum(_nonspace(c["chunk"]) for c in rows),
        },
        "chunks": out_chunks,
    }


# ---------- public ----------


def inspect_document(
    text: str, *, name: str, page_spans=None, preview_chars: int = 150, profiles: tuple[str, ...] = ("flashcards", "revision")
) -> dict:
    headings = find_headings(text)
    return {
        "document": {
            "name": name,
            "chars": len(text),
            "lines": text.count("\n") + 1,
            "pages": len(page_spans) if page_spans else None,
            "page_info": "available (recomputed from the uploaded PDF)"
            if page_spans
            else "NOT available: the app stores only plain text, page numbers are discarded in extract.py",
            "note_char_limit": MAX_NOTES_CHARS,
        },
        "quiz_and_paper_context": {
            "direct_context_limit": DIRECT_CONTEXT_CHARS,
            "source": "full notes" if len(text) <= DIRECT_CONTEXT_CHARS else "AI-written revision summary (notes are too long)",
        },
        "sentence_units": _unit_stats(text, preview_chars),
        "headings_heuristic": [h["text"] for h in headings][:40],
        "profiles": {
            key: _inspect_profile(text, name, PROFILES[key], headings, page_spans, preview_chars) for key in profiles
        },
    }


# ---------- readable report for the terminal ----------


def render_report(result: dict, *, show_chunks: bool = True) -> str:
    d, u = result["document"], result["sentence_units"]
    L = [
        "=" * 78,
        f"DOCUMENT  {d['name']}",
        f"  chars={d['chars']:,}  lines={d['lines']:,}  pages={d['pages'] or 'n/a'}",
        f"  page info: {d['page_info']}",
        f"  quiz/paper context: {result['quiz_and_paper_context']['source']} (limit {result['quiz_and_paper_context']['direct_context_limit']:,} chars)",
        "",
        "SENTENCE UNITS (the pieces the chunker packs together)",
        f"  {u['what']}",
        f"  count={u['count']:,}  chars min/avg/max = {u['chars_min']}/{u['chars_avg']}/{u['chars_max']}",
        f"  shorter than 25 chars: {u['short_under_25_chars']}   not ending like a sentence: {u['not_ending_like_a_sentence']}",
        f"  long lines without end punctuation: {u['long_lines_without_end_punctuation']} of {u['lines_total']} lines"
        f"  -> hard-wrapped text: {'YES' if u['looks_like_hard_wrapped_text'] else 'no'}",
    ]
    for ex in u["short_examples"][:5]:
        L.append(f"    short unit #{ex['unit']}: {ex['text']!r}")
    L.append(f"  headings found (heuristic): {len(result['headings_heuristic'])}  e.g. {result['headings_heuristic'][:5]}")

    for key, p in result["profiles"].items():
        s = p["summary"]
        L += [
            "",
            "-" * 78,
            f"PROFILE {key}: chunk size {p['chunk_chars']:,} chars, overlap {p['overlap_chars']}, "
            f"max {p['max_chunks_used_per_generation']} chunks used ({p['used_by']})",
            f"  chunks={p['chunk_count']} (used {p['chunks_used']}, chars in unused chunks {p['chars_in_unused_chunks']:,})"
            f"  size min/avg/max = {p['chunk_chars_min']:,}/{p['chunk_chars_avg']:,}/{p['chunk_chars_max']:,}",
            f"  boundaries: {s['boundaries_between_chunks']}   cuts ending mid-sentence: {s['cuts_that_end_mid_sentence']}",
            f"  headings: found {s['headings_found']}, left as last line of a chunk {s['headings_left_as_last_line_of_a_chunk']}, "
            f"glued into a sentence unit {s['headings_glued_into_a_sentence_unit']}",
            f"  structure flattened: {s['newlines_turned_into_spaces']:,} newlines + {s['blank_lines_turned_into_spaces']:,} blank lines became spaces",
            f"  non-space characters lost: {s['non_space_chars_lost']}",
        ]
        if not show_chunks:
            continue
        for c in p["chunks"]:
            st = c["structure"]
            L += [
                "",
                f"  [chunk {c['index']}] {'USED' if c['used'] else 'NOT USED'}  {c['chars']:,} chars"
                f"{'  (OVER LIMIT)' if c['over_size_limit'] else ''}"
                f"  | original chars {c['original_start']:,}-{c['original_end']:,}, lines {c['original_lines']}"
                f"{', pages ' + c['pages'] if c['pages'] else ''}",
                f"     next boundary: {c['break_after'] or '(end of document)'}   starts mid-sentence: {c['starts_mid_sentence']}   ends mid-sentence: {c['ends_mid_sentence']}",
                f"     starts: {c['preview_start']!r}",
                f"     ends:   {c['preview_end']!r}",
                f"     original start (newlines visible): {c['original_preview_start']!r}",
                f"     headings inside: {st['headings_in_span']}   last line is a heading: {st['heading_is_last_line_of_chunk']}",
                f"     {st['newlines_turned_into_spaces']} newlines / {st['blank_lines_turned_into_spaces']} blank lines flattened,"
                f" {st['paragraph_blocks_in_span']} paragraph blocks, {st['sentence_units_in_chunk']} sentence units",
            ]
            for g in st["headings_glued_into_a_sentence_unit"]:
                L.append(f"     GLUED: heading {g['heading']!r} is the start of the unit {g['unit_starts_with']!r}")
    L.append("=" * 78)
    return "\n".join(L)
