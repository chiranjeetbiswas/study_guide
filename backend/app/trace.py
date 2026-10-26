"""Observability for the generation pipeline (RAG Phase 1a).

Nothing here changes what the pipeline does. It records what happened so it can be inspected afterwards:
for each generation "run" (revision notes, quiz, paper, flashcards) it keeps every Groq call with its
prompt size, latency and token usage, and which chunk (if any) the call was made for.

Runs are saved in the `generation_runs` collection and read back through the /debug endpoints.
Recording must never break a feature, so every storage step swallows its own errors.

Python threads don't inherit contextvars, so code that fans work out to a ThreadPoolExecutor uses
map_in_context() to hand each task the caller's run.
"""

import logging
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from datetime import datetime, timezone

log = logging.getLogger("trace")

_current_run: ContextVar["Run | None"] = ContextVar("current_run", default=None)
_current_chunk: ContextVar[int | None] = ContextVar("current_chunk", default=None)

PREVIEW_CHARS = 160


def _num(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


class Run:
    def __init__(self, kind: str, set_id, meta: dict):
        self.kind = kind
        self.set_id = set_id
        self.meta = dict(meta)
        self.counters: dict[str, int] = {}
        self.calls: list[dict] = []
        self.chunks: dict[int, dict] = {}
        self.started = time.perf_counter()
        self.created_at = datetime.now(timezone.utc)
        self._lock = threading.Lock()  # chunks are processed in parallel threads

    def add_call(self, label: str, request: dict, completion, latency_ms: float, error: str | None):
        messages = request.get("messages", [])
        system_chars = sum(len(m["content"]) for m in messages if m["role"] == "system")
        user_chars = sum(len(m["content"]) for m in messages if m["role"] != "system")
        user_text = next((m["content"] for m in reversed(messages) if m["role"] != "system"), "")

        response_chars, finish_reason, usage = 0, None, {}
        if completion is not None:
            choice = completion.choices[0]
            response_chars = len(choice.message.content or "")
            finish_reason = choice.finish_reason
            raw_usage = getattr(completion, "usage", None)
            if raw_usage is not None:
                dumped = raw_usage.model_dump() if hasattr(raw_usage, "model_dump") else dict(raw_usage)
                # Groq also reports queue/prompt/completion times (seconds) next to the token counts
                usage = {k: v for k, v in dumped.items() if _num(v)}
                details = dumped.get("completion_tokens_details")
                if isinstance(details, dict) and _num(details.get("reasoning_tokens")):
                    usage["reasoning_tokens"] = details["reasoning_tokens"]

        call = {
            "label": label,
            "chunk": _current_chunk.get(),
            "model": request.get("model"),
            "latency_ms": round(latency_ms),
            "system_chars": system_chars,
            "user_chars": user_chars,
            "prompt_chars": system_chars + user_chars,
            "response_chars": response_chars,
            "finish_reason": finish_reason,
            "usage": usage,
            "error": error,
            "user_prompt_start": user_text[:PREVIEW_CHARS],
            "user_prompt_end": user_text[-PREVIEW_CHARS:] if len(user_text) > PREVIEW_CHARS else "",
        }
        with self._lock:
            call["order"] = len(self.calls)
            self.calls.append(call)

    def to_document(self, user_id, status: str, error: str | None) -> dict:
        total_ms = round((time.perf_counter() - self.started) * 1000)
        calls = sorted(self.calls, key=lambda c: c["order"])

        def total(field: str) -> int:
            return round(sum(c["usage"].get(field, 0) for c in calls))

        chunks = []
        for index in sorted(self.chunks):
            info = dict(self.chunks[index])
            mine = [c for c in calls if c["chunk"] == index]
            info.update(
                index=index,
                calls=len(mine),
                prompt_chars=sum(c["prompt_chars"] for c in mine),
                latency_ms=sum(c["latency_ms"] for c in mine),
                total_tokens=round(sum(c["usage"].get("total_tokens", 0) for c in mine)),
            )
            chunks.append(info)

        return {
            "user_id": user_id,
            "set_id": self.set_id,
            "kind": self.kind,
            "status": status,
            "error": error,
            "created_at": self.created_at,
            "total_ms": total_ms,  # wall clock; less than the sum of call latencies when chunks run in parallel
            "meta": self.meta,
            "counters": self.counters,
            "totals": {
                "calls": len(calls),
                "calls_latency_ms": sum(c["latency_ms"] for c in calls),
                "prompt_chars": sum(c["prompt_chars"] for c in calls),
                "response_chars": sum(c["response_chars"] for c in calls),
                "prompt_tokens": total("prompt_tokens"),
                "completion_tokens": total("completion_tokens"),
                "total_tokens": total("total_tokens"),
                "reasoning_tokens": total("reasoning_tokens"),
            },
            "chunks": chunks,
            "calls": calls,
        }


@contextmanager
def traced(db, user: dict, kind: str, set_id, **meta):
    """Records everything the pipeline does inside the block as one saved run."""
    run = Run(kind, set_id, meta)
    token = _current_run.set(run)
    status, error = "ok", None
    try:
        yield run
    except BaseException as e:
        status, error = "error", f"{type(e).__name__}: {getattr(e, 'detail', e)}"[:300]
        raise
    finally:
        _current_run.reset(token)
        try:
            db.generation_runs.insert_one(run.to_document(user["_id"], status, error))
        except Exception:
            log.exception("could not save generation run")


def traced_create(client, label: str, **kwargs):
    """client.chat.completions.create(**kwargs), plus timing and usage recorded on the current run."""
    run = _current_run.get()
    start = time.perf_counter()
    try:
        completion = client.chat.completions.create(**kwargs)
    except Exception as e:
        if run:
            run.add_call(label, kwargs, None, (time.perf_counter() - start) * 1000, type(e).__name__)
        raise
    if run:
        try:
            run.add_call(label, kwargs, completion, (time.perf_counter() - start) * 1000, None)
        except Exception:
            log.exception("could not record call")
    return completion


def meta(**values):
    """Adds facts to the current run (no-op outside a run)."""
    run = _current_run.get()
    if run:
        run.meta.update(values)


def count(name: str, amount: int = 1):
    run = _current_run.get()
    if run:
        with run._lock:
            run.counters[name] = run.counters.get(name, 0) + amount


def current_chunk() -> int | None:
    return _current_chunk.get()


def chunk_result(**values):
    """Adds facts about the chunk being processed (set by chunk_scope)."""
    run, index = _current_run.get(), _current_chunk.get()
    if run and index is not None:
        with run._lock:
            run.chunks.setdefault(index, {}).update(values)


@contextmanager
def chunk_scope(index: int, **values):
    """Marks the Groq calls made inside the block as belonging to chunk `index`."""
    token = _current_chunk.set(index)
    try:
        chunk_result(**values)
        yield
    finally:
        _current_chunk.reset(token)


def map_in_context(pool, fn, items: list[tuple]) -> list:
    """list(pool.map(fn, items)) where each tuple in items is unpacked into fn, and every task sees
    the current run (worker threads don't inherit contextvars)."""
    contexts = [copy_context() for _ in items]
    return list(pool.map(lambda pair: pair[0].run(fn, *pair[1]), zip(contexts, items)))
