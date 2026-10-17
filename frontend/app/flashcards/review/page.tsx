"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import ReviewCard from "@/components/ReviewCard";
import { api, type Card, type CheckStats } from "@/lib/api";

export default function ReviewPage() {
  const [cards, setCards] = useState<Card[] | null>(null);
  const [stats, setStats] = useState<CheckStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Stats are a nice-to-have; ignore failures
    api.checkStats().then(setStats).catch(() => {});
    api
      .listCards("pending")
      .then(setCards)
      .catch((err) => setError(err instanceof Error ? err.message : "Something went wrong"));
  }, []);

  const remove = (id: string) => setCards((prev) => prev?.filter((c) => c.id !== id) ?? null);
  const flaggedInQueue = cards?.filter((c) => c.check_status === "flagged").length ?? 0;

  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight text-stone-800">Review queue</h1>
      <p className="mt-2 text-stone-600">Check each card against the sentence it came from, then approve, edit or reject it.</p>

      {stats && stats.checked > 0 && (
        <p className="mt-4 text-sm text-stone-500">
          Accuracy check, all time: {stats.flagged} of {stats.checked} generated cards flagged (
          {Math.round(stats.flagged_rate * 100)}%).
        </p>
      )}

      {error && (
        <p role="alert" className="mt-6 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
          {error}
        </p>
      )}

      {!error && cards === null && <p className="mt-8 text-stone-500">Loading…</p>}

      {cards && cards.length === 0 && (
        <div className="mt-8 rounded-2xl border border-dashed border-stone-300 p-10 text-center text-stone-500">
          Nothing to review.{" "}
          <Link href="/sets" className="font-medium text-teal-700 underline underline-offset-2">
            Generate some cards
          </Link>
        </div>
      )}

      {cards && cards.length > 0 && (
        <>
          <p className="mt-6 text-sm text-stone-500">
            {cards.length} waiting
            {flaggedInQueue > 0 && <span className="text-amber-700"> · {flaggedInQueue} flagged for a closer look</span>}
          </p>
          <div className="mt-3 space-y-4">
            {cards.map((card) => (
              <ReviewCard key={card.id} card={card} onResolved={remove} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
