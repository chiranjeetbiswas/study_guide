# AI Study Guide

Upload your notes (up to 3 PDF or text files) and get revision notes, practice quizzes, exam papers and spaced-repetition
flashcards. Then **ask questions about your notes** and get answers that come only from what you uploaded, with the exact
passages shown and a second AI that fact-checks every answer before you see it.

Built with FastAPI, MongoDB, Next.js and a retrieval-augmented generation (RAG) pipeline written from scratch.

## What it does

- **Study sets from up to 3 files.** Mix PDFs and `.txt` files. Each file is cleaned and chunked on its own.
- **Revision notes** with topics, key points, terms and likely exam questions.
- **Multiple-choice quiz** with an explanation after every answer.
- **Exam papers** with the total marks and duration you choose.
- **Flashcards with spaced repetition** (SM-2). Cards come back when you are about to forget them. Each AI-written card is
  checked against your notes, and unsupported ones are flagged.
- **Ask your notes.** Answers cite their sources (file, heading, page). If your notes do not cover the question, it says so
  instead of guessing. Follow-up questions work ("explain that more").
- **Fact-checked answers.** A reviewer agent checks each answer against the retrieved passages. If a claim is not supported,
  the answer is rewritten, up to 3 attempts. Anything still unverified is shown with a warning.

## How the RAG pipeline works

```
 INDEXING (once per study set)
 files ─> extract ─> clean ─> chunk ─> embed ─> MongoDB
          (pypdf)    remove     ~1200 chars   local model
                     repeated   + 200 overlap (384 numbers
                     headers,   page + heading per chunk)
                     find
                     headings        each file is processed separately

 QUERYING (every question)
 question + last 3 turns
    │
    ▼
 [1] rewrite follow-ups into a standalone question        (only when there is history)
    ▼
 [2] hybrid search: BM25 keywords + embedding similarity,
     merged with Reciprocal Rank Fusion  ─> top 5 chunks
    ▼
 [3] generator answers using ONLY those chunks
    ▼
 [4] reviewer checks every claim against the chunks
     unsupported? ─> feedback to the generator ─> new answer (max 3 attempts)
    ▼
 answer + citations + source passages + verification status
```

| Stage | Code |
|---|---|
| Cleaning and structure-aware chunking | `backend/app/chunking.py`, `chunk_store.py` |
| Multiple files per set | `backend/app/documents.py` |
| Local embeddings (fastembed, `BAAI/bge-small-en-v1.5`) | `backend/app/embeddings.py` |
| Keyword, vector and hybrid search | `backend/app/retrieval.py` |
| Question answering and conversation memory | `backend/app/ask.py` |
| Generate, review, retry loop | `backend/app/verify.py` |

## Measured results

Retrieval quality on a 34-question set written against a sample biology chapter
(`backend/samples/eval_questions.json`). *MRR* is the average of 1 divided by the position of the first correct chunk, so
1.0 means the right chunk was always first.

| Search method | hit@1 | hit@5 | MRR |
|---|---|---|---|
| Embeddings only | 0.65 | 0.97 | 0.78 |
| Keywords only (BM25) | 0.77 | 0.94 | 0.84 |
| **Hybrid (used by the app)** | **0.82** | **1.00** | **0.90** |

Each single method has a blind spot: embeddings are weak on exact terms, names and numbers, and keywords are weak on
synonyms. Hybrid is never the worst in any question group.

The fact-checking reviewer was tried on hand-made answers (correct, reworded, wrong number, wrong place, and a fact that is
true in real life but not in the notes). It judged all 5 kinds correctly in 3 runs each.

**Limits of these numbers:** the evaluation set is small, uses one document, and was written by the author. Treat them as
evidence that the approach works, not as a benchmark. An end-to-end answer-quality evaluation
(`backend/eval_answers.py`) is written but has not produced results yet.

## Tech stack

- **Backend:** Python, FastAPI, MongoDB (PyMongo), JWT auth with argon2 password hashing
- **AI:** Groq (`openai/gpt-oss-120b`) for generation, fastembed (ONNX) for local embeddings, pypdf for PDF text
- **Frontend:** Next.js, React, TypeScript, Tailwind CSS

## Getting started

### Prerequisites

- Python 3.10 or newer
- Node.js 20 or newer
- MongoDB running locally on port 27017 (or a MongoDB Atlas connection string)
- A free [Groq API key](https://console.groq.com)

### 1. Backend

```bash
cd backend
python -m venv .venv
# Windows:  .venv\Scripts\activate        macOS/Linux:  source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env        # then edit .env: add your GROQ_API_KEY and a JWT_SECRET
python -m uvicorn app.main:app --reload --port 8000
```

API docs are at http://localhost:8000/docs. The first request that creates a study set downloads the embedding model
(about 100 MB) into `backend/.model_cache/`.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000, sign up, and upload some notes.

### Configuration (`backend/.env`)

| Variable | Required | Purpose |
|---|---|---|
| `GROQ_API_KEY` | yes | Groq API key |
| `JWT_SECRET` | yes | Signs login tokens, at least 32 random characters |
| `MONGODB_URL`, `MONGODB_DB` | no | Defaults: `mongodb://localhost:27017`, `study_guide` |
| `FRONTEND_ORIGIN` | for CORS | The frontend's URL. Use `http://localhost:3000` locally |
| `REVIEW_MODEL` | no | A different model for the fact-checker (default: same as the generator) |
| `CHUNK_SIZE`, `CHUNK_OVERLAP` | no | Chunking settings (default 1200 and 200 characters) |
| `EMBED_MODEL` | no | Embedding model (default `BAAI/bge-small-en-v1.5`) |

The frontend reads `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`).

## Tests and evaluation

```bash
cd backend
python -m unittest discover -s tests          # 84 tests, no server or AI key needed
python eval_retrieval.py --show-misses        # compare keyword, vector and hybrid search
python eval_retrieval.py --chunk-size 800 --chunk-overlap 133   # try other chunk settings
python eval_answers.py --limit 8              # full answer pipeline on a few questions (uses the Groq API)
```

## Main API endpoints

| Endpoint | What it does |
|---|---|
| `POST /auth/signup`, `POST /auth/login`, `GET /auth/me` | Accounts |
| `POST /sets`, `POST /sets/upload` | Create a set from pasted text, or from 1 to 3 uploaded files |
| `POST /sets/{id}/revision`, `/quiz`, `/paper`, `/flashcards` | Generate study material |
| `POST /sets/{id}/ask` | Ask your notes (`history`, `mode`, `verify` options) |
| `GET /sets/{id}/chunks`, `/chunks/search` | Inspect chunks and try the search modes |
| `GET /quiz/due`, `POST /cards/{id}/review` | Spaced-repetition review |

`/debug/*` endpoints expose pipeline internals for development. Remove or protect them before a public deployment.

## Known limitations

- Scanned PDFs are not supported (no OCR). Limits: 3 files per set, 5 MB and 100 pages per file.
- The reviewer checks that an answer is supported by the notes. It does not check for missing information.
- The generator and reviewer use the same model by default, so the second opinion is not fully independent. Set
  `REVIEW_MODEL` to use a different one.
- Each question rewrites follow-ups using only the last 3 turns.
- Free Groq accounts have daily and per-minute token limits, which can slow or pause the AI features.

## Troubleshooting (Windows)

If `pip.exe` or `uvicorn.exe` is blocked by Windows Application Control, call them through Python instead:
`python -m pip ...` and `python -m uvicorn ...`.
