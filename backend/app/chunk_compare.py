"""Old chunker vs new chunker, side by side (RAG Phase 1b).

Phase 1a's inspector (inspector.py) is unchanged and still describes the old chunker. This module runs the
new pipeline (chunking.py) on the same document and puts the numbers next to the old ones, so you can see
what a change of chunk size or overlap did.
"""

import re
from collections import Counter
from statistics import mean

from app.chunking import _TERMINAL, Page, chunk_document, pages_from_text
from app.flashcards import CHUNK_CHARS, _split_chunks
from app.inspector import _inspect_profile, find_headings


def _nonspace(text: str) -> int:
    return sum(1 for ch in text if not ch.isspace())


def _page_spans(pages: list[str] | None) -> list[tuple[int, int, int]] | None:
    """(page, start, end) offsets of each page inside the document text (joined with newlines, then stripped)."""
    if not pages:
        return None
    raw = "\n".join(pages)
    lead = len(raw) - len(raw.lstrip())
    spans, pos = [], 0
    for number, text in enumerate(pages, start=1):
        spans.append((number, max(pos - lead, 0), max(pos + len(text) - lead, 0)))
        pos += len(text) + 1
    return spans


def _old_metrics(text: str, headings: list[dict], spans, size: int, noise: list[dict], preview: int) -> dict:
    profile = _inspect_profile(text, "doc", {"size": size, "max_chunks": 10**6, "used_by": ""}, headings, spans, preview)
    chunks = _split_chunks(text, size)
    joined = " ".join(chunks)
    footer_hits = 0
    for entry in noise:
        pattern = re.escape(entry["key"]).replace(r"\#", r"\d+")
        footer_hits += len(re.findall(pattern, joined, flags=re.IGNORECASE))
    summary = profile["summary"]
    boundaries = summary["boundaries_between_chunks"]
    return {
        "chunk_size_setting": f"{size}",
        "chunks": profile["chunk_count"],
        "chars_min_avg_max": (profile["chunk_chars_min"], profile["chunk_chars_avg"], profile["chunk_chars_max"]),
        "overlap": "none",
        "ends_mid_sentence": f"{summary['cuts_that_end_mid_sentence']}/{max(profile['chunk_count'] - 1, 0)}",
        "boundary_kinds": f"{boundaries['paragraph_break']} paragraph / {boundaries['line_break']} line / {boundaries['same_line']} mid-line",
        "headings_glued_into_text": summary["headings_glued_into_a_sentence_unit"],
        "headings_stranded_at_chunk_end": summary["headings_left_as_last_line_of_a_chunk"],
        "page_header_footer_lines_inside_chunks": footer_hits,
        "chunks_with_page_number": "0 (not stored)",
        "chunks_with_heading_or_section": "0 (not stored)",
        "structure": f"{summary['newlines_turned_into_spaces']} newlines became spaces",
        "chunk_rows": profile["chunks"],
    }


def _new_metrics(result, preview: int) -> dict:
    chunks = result.chunks
    inner = chunks[:-1]  # the last chunk always ends at the end of the document
    kinds = Counter(c.end_kind for c in inner)
    headings = [b for b in result.blocks if b.kind == "heading"]
    contents = [len(c.content) for c in chunks]
    own = [len(c.own_text) for c in chunks]
    lines_intact = sum(
        1 for c in chunks for h in c.headings if any(line.strip() == h for line in c.own_text.split("\n"))
    )
    heading_total_in_chunks = sum(len(c.headings) for c in chunks)
    lost = sum(_nonspace(b.text) for b in result.blocks) - sum(_nonspace(c.own_text) for c in chunks)
    return {
        "chunk_size_setting": f"{result.size} (+{result.overlap} overlap)",
        "chunks": len(chunks),
        "chars_min_avg_max": (min(contents, default=0), round(mean(contents)) if contents else 0, max(contents, default=0)),
        "new_text_chars_min_avg_max": (min(own, default=0), round(mean(own)) if own else 0, max(own, default=0)),
        "overlap": f"avg {round(mean(c.overlap_chars for c in chunks[1:])) if len(chunks) > 1 else 0} chars"
        f" ({round(100 * sum(c.overlap_chars for c in chunks) / max(sum(contents), 1))}% of stored text)",
        "ends_mid_sentence": f"{kinds['word']}/{len(inner)}",
        "ends_at_sentence_punctuation": f"{sum(1 for c in inner if _TERMINAL.search(c.own_text.rstrip()))}/{len(inner)}",
        "boundary_kinds": f"{kinds['block']} paragraph-or-block / {kinds['sentence']} inside a paragraph (at a sentence end) / {kinds['word']} inside a sentence",
        "headings_glued_into_text": heading_total_in_chunks - lines_intact,
        "headings_stranded_at_chunk_end": sum(1 for c in inner if c.block_kinds and c.block_kinds[-1] == "heading"),
        "page_header_footer_lines_inside_chunks": 0
        if not any(re.search(re.escape(n["example"]), c.content) for n in result.noise_removed for c in chunks)
        else "FOUND",
        "chunks_with_page_number": f"{sum(1 for c in chunks if c.page_number is not None)}/{len(chunks)}",
        "chunks_with_heading_or_section": f"{sum(1 for c in chunks if c.heading or c.section)}/{len(chunks)}",
        "structure": f"{len(headings)} headings and {sum(1 for b in result.blocks if b.kind != 'heading')} paragraphs/list items kept as separate blocks",
        "non_space_chars_lost": lost,
        "noise_removed": result.noise_removed,
        "chunk_rows": [
            {
                "index": c.index,
                "chars": len(c.content),
                "new_text_chars": len(c.own_text),
                "overlap_chars": c.overlap_chars,
                "pages": None if c.page_number is None else (str(c.page_number) if c.page_end is None else f"{c.page_number}-{c.page_end}"),
                "section": c.section,
                "heading": c.heading,
                "headings_inside": c.headings,
                "end_kind": c.end_kind,
                "preview_start": c.content[:preview],
                "preview_end": c.content[-preview:],
                "overlap_text": c.content[: c.overlap_chars],
            }
            for c in chunks
        ],
    }


def compare(text: str, pages: list[str] | None, *, size: int, overlap: int, preview_chars: int = 110) -> dict:
    """Old chunker (as the app uses it today, and at the same size as the new one) vs the new chunker."""
    text = text.strip()
    page_objs = [Page(i + 1, t) for i, t in enumerate(pages)] if pages else pages_from_text(text)
    new = chunk_document(page_objs, size=size, overlap=overlap)
    headings = find_headings(text)
    spans = _page_spans(pages)
    # keys of the page headers/footers the new cleaning removed, to count how many the old chunks still contain
    from app.chunking import _edge_key

    noise = [{**n, "key": _edge_key(n["example"])} for n in new.noise_removed]
    return {
        "document_chars": len(text),
        "pages": len(pages) if pages else None,
        "old_as_used_today": _old_metrics(text, headings, spans, CHUNK_CHARS, noise, preview_chars),
        "old_at_new_size": _old_metrics(text, headings, spans, size, noise, preview_chars),
        "new": _new_metrics(new, preview_chars),
    }


def sweep(text: str, pages: list[str] | None, grid: list[tuple[int, int]]) -> list[dict]:
    text = text.strip()
    page_objs = [Page(i + 1, t) for i, t in enumerate(pages)] if pages else pages_from_text(text)
    rows = []
    for size, overlap in grid:
        result = chunk_document(page_objs, size=size, overlap=overlap)
        chunks, inner = result.chunks, result.chunks[:-1]
        kinds = Counter(c.end_kind for c in inner)
        contents = [len(c.content) for c in chunks]
        rows.append(
            {
                "size": size,
                "overlap": overlap,
                "chunks": len(chunks),
                "avg_new_text": round(mean(len(c.own_text) for c in chunks)),
                "avg_stored": round(mean(contents)),
                "max_stored": max(contents),
                "duplicate_pct": round(100 * sum(c.overlap_chars for c in chunks) / sum(contents)),
                "end_block": kinds["block"],
                "end_sentence": kinds["sentence"],
                "end_word": kinds["word"],
                "stranded_headings": sum(1 for c in inner if c.block_kinds and c.block_kinds[-1] == "heading"),
            }
        )
    return rows


# ---------- terminal report ----------


def render_comparison(result: dict, *, show: int = 3) -> str:
    cols = [("OLD (as used today)", result["old_as_used_today"]), ("OLD @ same size", result["old_at_new_size"]), ("NEW", result["new"])]
    rows = [
        ("chunk size setting", "chunk_size_setting"),
        ("chunks", "chunks"),
        ("chars min / avg / max", "chars_min_avg_max"),
        ("overlap", "overlap"),
        ("chunks that end mid-sentence", "ends_mid_sentence"),
        ("how chunks end", "boundary_kinds"),
        ("headings glued into body text", "headings_glued_into_text"),
        ("headings stranded at chunk end", "headings_stranded_at_chunk_end"),
        ("page header/footer lines in chunks", "page_header_footer_lines_inside_chunks"),
        ("chunks with a page number", "chunks_with_page_number"),
        ("chunks with heading/section", "chunks_with_heading_or_section"),
        ("structure", "structure"),
    ]
    width = 34
    lines = [
        "=" * 100,
        f"DOCUMENT  {result['document_chars']:,} chars, pages: {result['pages'] or 'n/a'}",
        "",
    ]
    for label, key in rows:
        lines.append(f"{label}")
        for title, col in cols:
            value = col.get(key, "-")
            if isinstance(value, tuple):
                value = " / ".join(f"{v:,}" for v in value)
            lines.append(f"    {title:<22}{value}")
    new = result["new"]
    lines += [
        "",
        f"new cleaning removed repeated page lines: {[(n['example'], n['times']) for n in new['noise_removed']] or 'none'}",
        f"new chunker: non-space characters lost = {new['non_space_chars_lost']} (0 means every character is in some chunk)",
        f"new chunker: new text per chunk min / avg / max = {' / '.join(str(v) for v in new['new_text_chars_min_avg_max'])}",
    ]
    for row in new["chunk_rows"][:show]:
        lines += [
            "",
            f"[new chunk {row['index']}] {row['chars']} chars ({row['new_text_chars']} new + {row['overlap_chars']} overlap)"
            f" | pages {row['pages'] or 'n/a'} | ends: {row['end_kind']}",
            f"    section: {row['section']!r}",
            f"    heading: {row['heading']!r}   headings inside: {row['headings_inside']}",
            f"    overlap text: {row['overlap_text']!r}" if row["overlap_chars"] else "    overlap text: (none, first chunk)",
            f"    starts: {row['preview_start']!r}",
            f"    ends:   {row['preview_end']!r}",
        ]
    lines.append("=" * 100)
    return "\n".join(lines)


def render_sweep(rows: list[dict]) -> str:
    head = f"{'size':>5} {'overlap':>7} {'chunks':>6} {'new txt avg':>11} {'stored avg':>10} {'stored max':>10} {'dup %':>5}  {'ends: block/sentence/word':<26} stranded"
    lines = [head, "-" * len(head)]
    for r in rows:
        ends = f"{r['end_block']}/{r['end_sentence']}/{r['end_word']}"
        lines.append(
            f"{r['size']:>5} {r['overlap']:>7} {r['chunks']:>6} {r['avg_new_text']:>11} {r['avg_stored']:>10} {r['max_stored']:>10} {r['duplicate_pct']:>5}  {ends:<26} {r['stranded_headings']}"
        )
    return "\n".join(lines)
