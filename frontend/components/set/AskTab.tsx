"use client";

import { useState } from "react";
import { api, type AskResult, type StudySet } from "@/lib/api";
import { ErrorBox, errorMessage, inputClass, primaryButton } from "./ui";

type Turn = { question: string; result: AskResult };

export default function AskTab({ set }: { set: StudySet }) {
  const [question, setQuestion] = useState("");
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
      const result = await api.askSet(set.id, q);
      setTurns((t) => [{ question: q, result }, ...t]);
      setQuestion("");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <form onSubmit={ask} className="flex flex-wrap gap-3">
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          maxLength={500}
          placeholder="Ask anything about these notes…"
          aria-label="Your question"
          className={`${inputClass} min-w-0 flex-1`}
        />
        <button type="submit" disabled={loading || question.trim().length < 3} className={primaryButton}>
          {loading ? "Searching your notes…" : "Ask"}
        </button>
      </form>
      <p className="mt-2 text-xs text-stone-500">
        Answers come only from your notes. The first question on an older set can take a little longer.
      </p>
      <ErrorBox message={error} />

      <ul className="mt-6 space-y-5">
        {turns.map((t, i) => (
          <li key={i} className="rounded-xl border border-stone-200 bg-white p-5 shadow-sm">
            <p className="text-sm font-medium text-stone-500">{t.question}</p>
            <p
              className={`mt-2 whitespace-pre-wrap ${t.result.found ? "text-stone-800" : "text-amber-800"}`}
            >
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
    </div>
  );
}
