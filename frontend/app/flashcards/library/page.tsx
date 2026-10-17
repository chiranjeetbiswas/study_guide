"use client";

import { useEffect, useMemo, useState } from "react";
import { api, type Card } from "@/lib/api";

export default function LibraryPage() {
  const [cards, setCards] = useState<Card[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    api
      .listCards("approved")
      .then(setCards)
      .catch((err) => setError(err instanceof Error ? err.message : "Something went wrong"));
  }, []);

  // Search runs in the browser over question, answer and source
  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!cards || !q) return cards;
    return cards.filter((c) => `${c.question} ${c.answer} ${c.source}`.toLowerCase().includes(q));
  }, [cards, query]);

  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight text-stone-800">Library</h1>
      <p className="mt-2 text-stone-600">Your approved cards.</p>

      <input
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search questions, answers and sources…"
        className="mt-6 w-full rounded-xl border border-stone-200 bg-white px-4 py-2.5 text-stone-800 shadow-sm outline-none placeholder:text-stone-400 focus:border-teal-600 focus:ring-2 focus:ring-teal-600/20"
      />

      {error && (
        <p role="alert" className="mt-6 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
          {error}
        </p>
      )}

      {!error && cards === null && <p className="mt-8 text-stone-500">Loading…</p>}

      {cards && cards.length === 0 && <p className="mt-8 text-stone-500">No approved cards yet.</p>}

      {cards && cards.length > 0 && visible && visible.length === 0 && (
        <p className="mt-8 text-stone-500">No cards match “{query}”.</p>
      )}

      {visible && visible.length > 0 && (
        <ul className="mt-6 space-y-3">
          {visible.map((card) => (
            <li key={card.id} className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
              <p className="font-medium text-stone-800">{card.question}</p>
              <p className="mt-1 text-stone-700">{card.answer}</p>
              <p className="mt-3 border-l-2 border-teal-600/40 pl-3 text-sm text-stone-500 italic">{card.source}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
