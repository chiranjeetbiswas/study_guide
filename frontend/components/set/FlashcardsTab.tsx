"use client";

import Link from "next/link";
import { useState } from "react";
import { api, type StudySet } from "@/lib/api";
import { EmptyState, ErrorBox, errorMessage, primaryButton } from "./ui";

export default function FlashcardsTab({ set, onChange }: { set: StudySet; onChange: (s: StudySet) => void }) {
  const [count, setCount] = useState(10);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [made, setMade] = useState<number | null>(null);

  async function generate() {
    setLoading(true);
    setError(null);
    setMade(null);
    try {
      const result = await api.makeSetFlashcards(set.id, count);
      setMade(result.cards.length);
      onChange({ ...set, card_count: set.card_count + result.cards.length });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <EmptyState
        title="Flashcards"
        text={
          set.card_count > 0
            ? `You have ${set.card_count} flashcards from this set. New cards wait in the review queue until you approve them.`
            : "Question-and-answer cards from your notes. Each card shows the line from your notes it came from, and waits in the review queue until you approve it."
        }
      >
        <label className="flex items-center gap-2 text-sm text-stone-600">
          Cards
          <select
            value={count}
            onChange={(e) => setCount(Number(e.target.value))}
            className="rounded-lg border border-stone-200 bg-white px-2 py-1.5 text-stone-800"
          >
            {[5, 10, 15, 20, 30].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        <button onClick={generate} disabled={loading} className={primaryButton}>
          {loading ? "Making cards…" : set.card_count > 0 ? "Make more cards" : "Make flashcards"}
        </button>
        {set.card_count > 0 && (
          <Link href="/flashcards/review" className="text-sm font-medium text-teal-700 underline underline-offset-2">
            Go to the review queue
          </Link>
        )}
      </EmptyState>
      {made !== null && (
        <p className="mt-4 rounded-lg border border-teal-200 bg-teal-50 px-4 py-3 text-sm text-teal-900">
          {made === 0
            ? "We couldn’t find clear facts to make cards from. Try different notes."
            : `Made ${made} card${made === 1 ? "" : "s"}. They’re waiting in the review queue.`}
        </p>
      )}
      <ErrorBox message={error} />
    </>
  );
}
