"use client";

import { useState } from "react";
import { api, type AskResult, type SearchMode, type StudySet } from "@/lib/api";
import { ErrorBox, errorMessage, inputClass, primaryButton, secondaryButton } from "./ui";

type Turn = { question: string; result: AskResult };

// How many earlier turns are sent along, so "explain that more" can be understood
const HISTORY_TURNS = 3;

const MODES: { value: SearchMode; label: string; hint: string }[] = [
  { value: "hybrid", label: "Hybrid", hint: "Meaning and exact words together (best overall)" },
  { value: "vector", label: "Meaning", hint: "Finds passages that mean the same, even in different words" },
  { value: "keyword", label: "Keywords", hint: "Finds passages that contain your exact words" },
];

export default function AskTab({ set }: { set: StudySet }) {
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState<SearchMode>("hybrid");
  // oldest first, so the newest answer is at the bottom, like a chat
  const [turns, setTurns] = useState<Turn[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function ask(e: React.FormEvent) {
    e.preventDefault();
    const q = question.trim();
    if (q.length < 3 || loading) return;
    setLoading(true);
    setError(null);
    try {
      const history = turns.slice(-HISTORY_TURNS).map((t) => ({ question: t.question, answer: t.result.answer }));
      const result = await api.askSet(set.id, q, history, mode);
      setTurns((t) => [...t, { question: q, result }]);
      setQuestion("");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <ul className="space-y-5">
        {turns.map((t, i) => (
          <li key={i} className="rounded-xl border border-stone-200 bg-white p-5 shadow-sm">
            <p className="text-sm font-medium text-stone-500">{t.question}</p>
            {t.result.search_query.trim() !== t.question && (
              <p className="mt-1 text-xs text-stone-400">Searched for: {t.result.search_query}</p>
            )}
            <p className={`mt-2 whitespace-pre-wrap ${t.result.found ? "text-stone-800" : "text-amber-800"}`}>
              {t.result.answer}
            </p>

            {t.result.sources.length > 0 && (
              <div className="mt-4 border-t border-stone-100 pt-3">
                <p className="text-xs font-medium uppercase tracking-wide text-stone-400">
                  {t.result.found ? "From your notes" : "Closest passages (probably not relevant)"}
                </p>
                <ul className="mt-2 space-y-2">
                  {t.result.sources.map((s) => (
                    <li key={s.number}>
                      <details className="rounded-lg bg-stone-50 px-3 py-2 text-sm">
                        <summary className="cursor-pointer text-stone-700">
                          <span className="font-medium">[{s.number}]</span>
                          {s.heading ? ` ${s.heading}` : ""}
                          {s.page_number ? ` · page ${s.page_number}` : ""}
                          {s.score !== null && <span className="text-stone-400"> · match {s.score.toFixed(2)}</span>}
                          <span className="text-stone-500"> — {s.snippet}</span>
                        </summary>
                        <p className="mt-2 whitespace-pre-wrap text-stone-600">{s.text}</p>
                      </details>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </li>
        ))}
      </ul>

      <ErrorBox message={error} />

      <form onSubmit={ask} className={`flex flex-wrap gap-3 ${turns.length > 0 ? "mt-6" : ""}`}>
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          maxLength={500}
          placeholder={turns.length > 0 ? "Ask a follow-up…" : "Ask anything about these notes…"}
          aria-label="Your question"
          className={`${inputClass} min-w-0 flex-1`}
        />
        <button type="submit" disabled={loading || question.trim().length < 3} className={primaryButton}>
          {loading ? "Searching your notes…" : "Ask"}
        </button>
      </form>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-xs text-stone-500">
        <label className="flex items-center gap-2">
          Search
          <select
            value={mode}
            onChange={(e) => setMode(e.target.value as SearchMode)}
            title={MODES.find((m) => m.value === mode)?.hint}
            className="rounded-lg border border-stone-200 bg-white px-2 py-1 text-stone-700"
          >
            {MODES.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
          <span className="hidden sm:inline">{MODES.find((m) => m.value === mode)?.hint}</span>
        </label>
        {turns.length > 0 && (
          <button type="button" onClick={() => setTurns([])} className={secondaryButton}>
            New conversation
          </button>
        )}
      </div>
      <p className="mt-2 text-xs text-stone-500">
        Answers come only from your notes. The first question on an older set can take a little longer.
      </p>
    </div>
  );
}
