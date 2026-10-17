"use client";

import { useState } from "react";
import { api, type Card } from "@/lib/api";

type Props = {
  card: Card;
  // Called after the card leaves the queue (approved or rejected)
  onResolved: (id: string) => void;
};

const field =
  "w-full rounded-lg border border-stone-200 bg-white p-2.5 text-stone-800 outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-600/20";

export default function ReviewCard({ card, onResolved }: Props) {
  const [current, setCurrent] = useState(card);
  const [editing, setEditing] = useState(false);
  const [question, setQuestion] = useState(card.question);
  const [answer, setAnswer] = useState(card.answer);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  const approve = () => run(async () => { await api.approve(current.id); onResolved(current.id); });
  const reject = () => run(async () => { await api.reject(current.id); onResolved(current.id); });
  const save = () =>
    run(async () => {
      setCurrent(await api.edit(current.id, { question, answer }));
      setEditing(false);
    });

  function cancelEdit() {
    setQuestion(current.question);
    setAnswer(current.answer);
    setEditing(false);
  }

  const flagged = current.check_status === "flagged";

  return (
    <article
      className={`rounded-2xl border bg-white p-5 shadow-sm ${flagged ? "border-amber-300" : "border-stone-200"}`}
    >
      {flagged && (
        <div role="note" className="mb-4 rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <p className="font-medium">⚠ Check this answer</p>
          <p className="mt-0.5 text-amber-800">
            {current.check_reason || "The answer may include information that isn’t in the source sentence."}
          </p>
        </div>
      )}
      <div className="grid gap-5 md:grid-cols-2">
        <div className="space-y-4">
          <div>
            <h3 className="text-xs font-medium uppercase tracking-wide text-stone-400">Question</h3>
            {editing ? (
              <textarea value={question} onChange={(e) => setQuestion(e.target.value)} rows={3} className={`mt-1 ${field}`} />
            ) : (
              <p className="mt-1 text-stone-800">{current.question}</p>
            )}
          </div>
          <div>
            <h3 className="text-xs font-medium uppercase tracking-wide text-stone-400">Answer</h3>
            {editing ? (
              <textarea value={answer} onChange={(e) => setAnswer(e.target.value)} rows={3} className={`mt-1 ${field}`} />
            ) : (
              <p className="mt-1 text-stone-800">{current.answer}</p>
            )}
          </div>
        </div>

        <div className="rounded-xl bg-stone-50 p-4">
          <h3 className="text-xs font-medium uppercase tracking-wide text-stone-400">From your notes</h3>
          <blockquote className="mt-1 border-l-2 border-teal-600/40 pl-3 text-stone-600 italic">
            {current.source}
          </blockquote>
        </div>
      </div>

      {error && (
        <p role="alert" className="mt-4 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-800">
          {error}
        </p>
      )}

      <div className="mt-5 flex items-center justify-end gap-2">
        {current.check_status === "supported" && (
          <span className="mr-auto text-xs text-teal-700">✓ Answer matches the source</span>
        )}
        {editing ? (
          <>
            <button onClick={cancelEdit} disabled={busy} className="rounded-full px-4 py-1.5 text-sm text-stone-600 hover:bg-stone-100">
              Cancel
            </button>
            <button
              onClick={save}
              disabled={busy || !question.trim() || !answer.trim()}
              className="rounded-full bg-teal-700 px-4 py-1.5 text-sm font-medium text-white hover:bg-teal-800 disabled:bg-stone-300"
            >
              Save
            </button>
          </>
        ) : (
          <>
            <button onClick={reject} disabled={busy} className="rounded-full px-4 py-1.5 text-sm text-rose-700 hover:bg-rose-50 disabled:opacity-50">
              Reject
            </button>
            <button onClick={() => setEditing(true)} disabled={busy} className="rounded-full border border-stone-200 px-4 py-1.5 text-sm text-stone-700 hover:bg-stone-50 disabled:opacity-50">
              Edit
            </button>
            <button onClick={approve} disabled={busy} className="rounded-full bg-teal-700 px-4 py-1.5 text-sm font-medium text-white hover:bg-teal-800 disabled:opacity-50">
              Approve
            </button>
          </>
        )}
      </div>
    </article>
  );
}
