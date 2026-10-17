"use client";

import { useState } from "react";
import { api, type StudySet } from "@/lib/api";
import { EmptyState, ErrorBox, errorMessage, primaryButton, secondaryButton } from "./ui";

export default function RevisionTab({ set, onChange }: { set: StudySet; onChange: (s: StudySet) => void }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function generate() {
    setLoading(true);
    setError(null);
    try {
      onChange(await api.makeRevision(set.id));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  if (!set.revision) {
    return (
      <>
        <EmptyState
          title="Revision notes"
          text="Your notes are turned into short, topic-by-topic revision notes with simple explanations, key points, important terms and likely exam questions."
        >
          <button onClick={generate} disabled={loading} className={primaryButton}>
            {loading ? "Making notes…" : "Make revision notes"}
          </button>
        </EmptyState>
        {loading && <p className="mt-3 text-center text-sm text-stone-500">Long notes can take a minute or two.</p>}
        <ErrorBox message={error} />
      </>
    );
  }

  return (
    <div className="print-area">
      <div className="no-print mb-4 flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-stone-500">{set.revision.length} topics</p>
        <div className="flex gap-2">
          <button onClick={() => window.print()} className={secondaryButton}>
            Print / save as PDF
          </button>
          <button onClick={generate} disabled={loading} className={secondaryButton}>
            {loading ? "Making notes…" : "Make again"}
          </button>
        </div>
      </div>
      <ErrorBox message={error} />

      <div className="space-y-5">
        {set.revision.map((t, i) => (
          <section key={i} className="break-inside-avoid rounded-xl border border-stone-200 bg-white p-5 shadow-sm">
            <h2 className="text-lg font-semibold text-stone-800">{t.title}</h2>

            {t.explanation && (
              <p className="mt-3 rounded-lg bg-teal-50 px-4 py-3 text-sm text-teal-900">
                <span className="font-medium">In simple words: </span>
                {t.explanation}
              </p>
            )}

            {t.key_points.length > 0 && (
              <>
                <h3 className="mt-4 text-xs font-medium uppercase tracking-wide text-stone-400">Key points</h3>
                <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-stone-700">
                  {t.key_points.map((p, j) => (
                    <li key={j}>{p}</li>
                  ))}
                </ul>
              </>
            )}

            {t.terms.length > 0 && (
              <>
                <h3 className="mt-4 text-xs font-medium uppercase tracking-wide text-stone-400">Important terms</h3>
                <dl className="mt-2 space-y-1 text-sm text-stone-700">
                  {t.terms.map((x, j) => (
                    <div key={j}>
                      <dt className="inline font-medium text-stone-800">{x.term}</dt>
                      <dd className="inline"> — {x.meaning}</dd>
                    </div>
                  ))}
                </dl>
              </>
            )}

            {t.likely_questions.length > 0 && (
              <>
                <h3 className="mt-4 text-xs font-medium uppercase tracking-wide text-stone-400">
                  Questions that may come
                </h3>
                <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-stone-700">
                  {t.likely_questions.map((q, j) => (
                    <li key={j}>{q}</li>
                  ))}
                </ul>
              </>
            )}
          </section>
        ))}
      </div>
    </div>
  );
}
