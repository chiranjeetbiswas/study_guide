"""Show how the current chunker splits a document. Needs no server, login or database.

    python inspect_chunks.py path/to/notes.pdf
    python inspect_chunks.py path/to/notes.txt --profile revision
    python inspect_chunks.py path/to/notes.pdf --json > baseline.json
    python inspect_chunks.py path/to/notes.pdf --summary        (no per-chunk detail)

Phase 1b: old chunker vs the new structured chunker
    python inspect_chunks.py path/to/notes.pdf --compare
    python inspect_chunks.py path/to/notes.pdf --compare --size 800 --overlap 100 --show 5
    python inspect_chunks.py path/to/notes.pdf --sweep 600:100,1200:200,2400:300
"""

import argparse
import json
import sys
from pathlib import Path

from app.chunking import CHUNK_OVERLAP, CHUNK_SIZE
from app.chunk_compare import compare, render_comparison, render_sweep, sweep
from app.extract import extract_document
from app.inspector import extract_with_pages, inspect_document, render_report

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("path", help=".pdf or .txt file")
parser.add_argument("--profile", choices=["both", "flashcards", "revision"], default="both")
parser.add_argument("--preview", type=int, default=150, help="characters shown at the start and end of each chunk")
parser.add_argument("--json", action="store_true", help="print the raw result as JSON")
parser.add_argument("--summary", action="store_true", help="skip the per-chunk detail")
parser.add_argument("--compare", action="store_true", help="old chunker vs the new structured chunker")
parser.add_argument("--size", type=int, default=CHUNK_SIZE, help="new chunker: characters of new text per chunk")
parser.add_argument("--overlap", type=int, default=CHUNK_OVERLAP, help="new chunker: characters repeated from the previous chunk")
parser.add_argument("--show", type=int, default=3, help="--compare: how many new chunks to print in full")
parser.add_argument("--sweep", help="try several settings, e.g. 600:100,1200:200,2400:300 (size:overlap)")
args = parser.parse_args()

path = Path(args.path)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to a narrower encoding

if args.compare or args.sweep:
    text, pages = extract_document(path.name, path.read_bytes())
    if args.sweep:
        grid = [tuple(int(n) for n in pair.split(":")) for pair in args.sweep.split(",")]
        print(render_sweep(sweep(text, pages, grid)))
    else:
        result = compare(text, pages, size=args.size, overlap=args.overlap)
        print(json.dumps(result, indent=2, ensure_ascii=False) if args.json else render_comparison(result, show=args.show))
    sys.exit(0)

text, spans = extract_with_pages(path.name, path.read_bytes())
profiles = ("flashcards", "revision") if args.profile == "both" else (args.profile,)
result = inspect_document(text, name=path.name, page_spans=spans, preview_chars=args.preview, profiles=profiles)

print(json.dumps(result, indent=2, ensure_ascii=False) if args.json else render_report(result, show_chunks=not args.summary))
