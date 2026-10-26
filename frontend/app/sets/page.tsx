"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type StudySetSummary } from "@/lib/api";

export default function SetsPage() {
  const [sets, setSets] = useState<StudySetSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listSets()
      .then(setSets)
      .catch((err) => setError(err instanceof Error ? err.message : "Something went wrong"));
  }, []);

  async function remove(id: string) {
    if (!window.confirm("Delete this study set and everything made from it?")) return;
    try {
      await api.deleteSet(id);
      setSets((prev) => prev?.filter((s) => s.id !== id) ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    }
  }

  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight text-stone-800">My sets</h1>
      <p className="mt-2 text-stone-600">Each set holds your notes and everything made from them.</p>

      {error && (
        <p role="alert" className="mt-6 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
          {error}
        </p>
      )}
      {sets === null && !error && <p className="mt-8 text-stone-500">Loading…</p>}
      {sets && sets.length === 0 && (
        <div className="mt-8 rounded-2xl border border-dashed border-stone-300 p-10 text-center text-stone-500">
          No study sets yet.{" "}
          <Link href="/" className="font-medium text-teal-700 underline underline-offset-2">
            Create your first one
          </Link>
        </div>
      )}

      <ul className="mt-6 space-y-3">
        {sets?.map((s) => (
          <li key={s.id} className="flex items-center justify-between gap-4 rounded-xl border border-stone-200 bg-white p-4 shadow-sm">
            <Link href={`/sets/${s.id}`} className="min-w-0 flex-1">
              <p className="truncate font-medium text-stone-800">{s.title}</p>
              <p className="mt-1 text-xs text-stone-500">
                {[s.level, s.files.length > 1 && `${s.files.length} files`, new Date(s.created_at).toLocaleDateString()]
                  .filter(Boolean)
                  .join(" · ")}
                {" · "}
                {[
                  s.has_revision && "notes",
                  s.has_quiz && "quiz",
                  s.paper_count > 0 && `${s.paper_count} paper${s.paper_count === 1 ? "" : "s"}`,
                  s.card_count > 0 && `${s.card_count} cards`,
                ]
                  .filter(Boolean)
                  .join(", ") || "nothing generated yet"}
              </p>
            </Link>
            <button onClick={() => remove(s.id)} className="rounded-full px-3 py-1.5 text-sm text-stone-400 hover:bg-stone-100 hover:text-rose-700">
              Delete
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
