"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type Card } from "@/lib/api";

export default function QuizPage() {
  const [queue, setQueue] = useState<Card[] | null>(null);
  const [index, setIndex] = useState(0);
  const [revealed, setRevealed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [knewCount, setKnewCount] = useState(0);
  const [lastInterval, setLastInterval] = useState<number | null>(null);

  useEffect(() => {
    api
      .dueCards()
      .then(setQueue)
      .catch((err) => setError(err instanceof Error ? err.message : "Something went wrong"));
  }, []);

  async function answer(knew: boolean) {
    if (!queue) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await api.review(queue[index].id, knew);
      if (knew) setKnewCount((n) => n + 1);
      setLastInterval(updated.interval_days);
      setIndex((i) => i + 1);
      setRevealed(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  const done = queue !== null && index >= queue.length;
  const card = queue && !done ? queue[index] : null;

  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight text-stone-800">Quiz</h1>

      {error && (
        <p role="alert" className="mt-6 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
          {error}
        </p>
      )}

      {!error && queue === null && <p className="mt-8 text-stone-500">Loading…</p>}

      {queue && queue.length === 0 && (
        <div className="mt-8 rounded-2xl border border-dashed border-stone-300 p-10 text-center text-stone-500">
          Nothing is due right now.{" "}
          <Link href="/flashcards/review" className="font-medium text-teal-700 underline underline-offset-2">
            Approve more cards
          </Link>{" "}
          or come back later.
        </div>
      )}

      {card && queue && (
        <div className="mt-6">
          <div className="mb-3 flex items-center justify-between text-sm text-stone-500">
            <span>
              Card {index + 1} of {queue.length}
            </span>
            {lastInterval !== null && index > 0 && <span>Last card: back in {lastInterval} day{lastInterval === 1 ? "" : "s"}</span>}
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-stone-200">
            <div className="h-full bg-teal-600 transition-all" style={{ width: `${(index / queue.length) * 100}%` }} />
          </div>

          <article className="mt-6 rounded-2xl border border-stone-200 bg-white p-8 shadow-sm">
            <h2 className="text-xs font-medium uppercase tracking-wide text-stone-400">Question</h2>
            <p className="mt-2 text-xl text-stone-800">{card.question}</p>

            {revealed && (
              <div className="mt-8 border-t border-stone-100 pt-6">
                <h2 className="text-xs font-medium uppercase tracking-wide text-stone-400">Answer</h2>
                <p className="mt-2 text-lg text-stone-800">{card.answer}</p>
                <p className="mt-4 border-l-2 border-teal-600/40 pl-3 text-sm text-stone-500 italic">{card.source}</p>
              </div>
            )}
          </article>

          <div className="mt-6 flex justify-center gap-3">
            {!revealed ? (
              <button onClick={() => setRevealed(true)} className="rounded-full bg-teal-700 px-8 py-2.5 text-sm font-medium text-white hover:bg-teal-800">
                Show answer
              </button>
            ) : (
              <>
                <button
                  onClick={() => answer(false)}
                  disabled={busy}
                  className="rounded-full border border-stone-300 px-6 py-2.5 text-sm text-stone-700 hover:bg-stone-100 disabled:opacity-50"
                >
                  I didn’t know it
                </button>
                <button
                  onClick={() => answer(true)}
                  disabled={busy}
                  className="rounded-full bg-teal-700 px-6 py-2.5 text-sm font-medium text-white hover:bg-teal-800 disabled:opacity-50"
                >
                  I knew it
                </button>
              </>
            )}
          </div>
        </div>
      )}

      {done && queue && queue.length > 0 && (
        <div className="mt-8 rounded-2xl border border-teal-200 bg-teal-50 p-8 text-center text-teal-900">
          <p className="text-lg font-medium">Session complete</p>
          <p className="mt-1 text-sm">
            You knew {knewCount} of {queue.length}. Each card has been rescheduled.
          </p>
          <Link href="/flashcards/due" className="mt-4 inline-block text-sm font-medium underline underline-offset-2">
            Back to due cards
          </Link>
        </div>
      )}
    </div>
  );
}
