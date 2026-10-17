"use client";

import { useState } from "react";
import { api, type StudySet } from "@/lib/api";
import { EmptyState, ErrorBox, errorMessage, primaryButton, secondaryButton } from "./ui";

export default function QuizTab({ set, onChange }: { set: StudySet; onChange: (s: StudySet) => void }) {
  const [count, setCount] = useState(10);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // question index -> option the student picked
  const [picked, setPicked] = useState<Record<number, number>>({});

  async function generate() {
    setLoading(true);
    setError(null);
    try {
      onChange(await api.makeQuiz(set.id, count));
      setPicked({});
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  const countPicker = (
    <label className="flex items-center gap-2 text-sm text-stone-600">
      Questions
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
  );

  if (!set.quiz) {
    return (
      <>
        <EmptyState title="Practice quiz" text="Multiple-choice questions from your notes, with an explanation after every answer.">
          {countPicker}
          <button onClick={generate} disabled={loading} className={primaryButton}>
            {loading ? "Making quiz…" : "Make quiz"}
          </button>
        </EmptyState>
        <ErrorBox message={error} />
      </>
    );
  }

  const answered = Object.keys(picked).length;
  const correct = set.quiz.filter((q, i) => picked[i] === q.answer_index).length;

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-stone-600">
          Answered {answered} of {set.quiz.length}
          {answered > 0 && <span className="font-medium text-stone-800"> · Score {correct}/{answered}</span>}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <button onClick={() => setPicked({})} className={secondaryButton}>
            Start over
          </button>
          {countPicker}
          <button onClick={generate} disabled={loading} className={secondaryButton}>
            {loading ? "Making quiz…" : "New quiz"}
          </button>
        </div>
      </div>
      <ErrorBox message={error} />

      <ol className="space-y-5">
        {set.quiz.map((q, i) => {
          const choice = picked[i];
          const done = choice !== undefined;
          return (
            <li key={i} className="rounded-xl border border-stone-200 bg-white p-5 shadow-sm">
              <p className="font-medium text-stone-800">
                {i + 1}. {q.question}
              </p>
              <div className="mt-3 space-y-2">
                {q.options.map((opt, j) => {
                  let style = "border-stone-200 hover:border-teal-600";
                  if (done && j === q.answer_index) style = "border-emerald-500 bg-emerald-50 text-emerald-900";
                  else if (done && j === choice) style = "border-rose-400 bg-rose-50 text-rose-900";
                  else if (done) style = "border-stone-200 text-stone-400";
                  return (
                    <button
                      key={j}
                      disabled={done}
                      onClick={() => setPicked((p) => ({ ...p, [i]: j }))}
                      className={`block w-full rounded-lg border px-4 py-2 text-left text-sm transition-colors ${style}`}
                    >
                      {opt}
                    </button>
                  );
                })}
              </div>
              {done && q.explanation && <p className="mt-3 text-sm text-stone-600">{q.explanation}</p>}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
