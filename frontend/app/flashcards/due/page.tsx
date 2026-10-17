"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type Card } from "@/lib/api";

function dueLabel(card: Card) {
  if (!card.due_date) return "New";
  const today = new Date().toLocaleDateString("en-CA"); // local date as YYYY-MM-DD
  return card.due_date < today ? `Overdue (was ${card.due_date})` : "Due today";
}

export default function DuePage() {
  const [cards, setCards] = useState<Card[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .dueCards()
      .then(setCards)
      .catch((err) => setError(err instanceof Error ? err.message : "Something went wrong"));
  }, []);

  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight text-stone-800">Cards due today</h1>
      <p className="mt-2 text-stone-600">New cards, plus any whose review date has arrived.</p>

      {error && (
        <p role="alert" className="mt-6 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
          {error}
        </p>
      )}

      {!error && cards === null && <p className="mt-8 text-stone-500">Loading…</p>}

      {cards && cards.length === 0 && (
        <div className="mt-8 rounded-2xl border border-dashed border-stone-300 p-10 text-center text-stone-500">
          You’re all caught up. Nothing is due today.
        </div>
      )}

      {cards && cards.length > 0 && (
        <>
          <div className="mt-6 flex items-center justify-between">
            <p className="text-sm text-stone-500">{cards.length} due</p>
            <Link href="/flashcards/quiz" className="rounded-full bg-teal-700 px-5 py-2 text-sm font-medium text-white hover:bg-teal-800">
              Start quiz
            </Link>
          </div>
          <ul className="mt-4 space-y-3">
            {cards.map((card) => (
              <li key={card.id} className="flex items-start justify-between gap-4 rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
                <p className="text-stone-800">{card.question}</p>
                <span className="shrink-0 rounded-full bg-stone-100 px-3 py-1 text-xs text-stone-600">{dueLabel(card)}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
