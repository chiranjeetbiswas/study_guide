"use client";

import { useState } from "react";
import { api, type Paper, type StudySet } from "@/lib/api";
import { ErrorBox, errorMessage, inputClass, primaryButton, secondaryButton } from "./ui";

export default function PaperTab({ set, onChange }: { set: StudySet; onChange: (s: StudySet) => void }) {
  const [marks, setMarks] = useState("50");
  const [minutes, setMinutes] = useState("");
  const [details, setDetails] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showAnswers, setShowAnswers] = useState(false);
  // Which paper is open; null = the newest one
  const [openId, setOpenId] = useState<string | null>(null);

  const totalMarks = Number(marks);
  const marksOk = Number.isInteger(totalMarks) && totalMarks >= 5 && totalMarks <= 200;
  const papers = [...set.papers].reverse(); // newest first
  const paper: Paper | undefined = papers.find((p) => p.id === openId) ?? papers[0];

  async function generate(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const updated = await api.makePaper(set.id, {
        total_marks: totalMarks,
        duration_minutes: minutes ? Number(minutes) : null,
        details,
      });
      onChange(updated);
      setOpenId(updated.papers[updated.papers.length - 1].id);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  async function remove(p: Paper) {
    if (!window.confirm("Delete this paper?")) return;
    try {
      onChange(await api.deletePaper(set.id, p.id));
      setOpenId(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <div>
      <form onSubmit={generate} className="no-print rounded-xl border border-stone-200 bg-white p-5 shadow-sm">
        <p className="font-medium text-stone-800">Make an exam paper</p>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <label className="text-sm text-stone-600">
            Total marks
            <input
              type="number"
              min={5}
              max={200}
              value={marks}
              onChange={(e) => setMarks(e.target.value)}
              className={`mt-1 w-full ${inputClass}`}
            />
          </label>
          <label className="text-sm text-stone-600">
            Time in minutes <span className="text-stone-400">(optional)</span>
            <input
              type="number"
              min={5}
              max={600}
              value={minutes}
              onChange={(e) => setMinutes(e.target.value)}
              placeholder="e.g. 90"
              className={`mt-1 w-full ${inputClass}`}
            />
          </label>
        </div>
        <label className="mt-3 block text-sm text-stone-600">
          Extra details <span className="text-stone-400">(optional)</span>
          <textarea
            value={details}
            onChange={(e) => setDetails(e.target.value)}
            rows={2}
            maxLength={1000}
            placeholder="e.g. hard questions, include 5 MCQs, focus on the first two topics"
            className={`mt-1 w-full ${inputClass}`}
          />
        </label>
        <div className="mt-4 flex items-center justify-between gap-3">
          <p className="text-xs text-stone-400">{marksOk ? "" : "Enter marks between 5 and 200."}</p>
          <button type="submit" disabled={loading || !marksOk} className={primaryButton}>
            {loading ? "Making paper…" : "Make paper"}
          </button>
        </div>
        {loading && <p className="mt-2 text-right text-xs text-stone-500">This can take up to a minute.</p>}
      </form>
      <div className="no-print">
        <ErrorBox message={error} />
      </div>

      {papers.length > 1 && (
        <div className="no-print mt-4 flex flex-wrap items-center gap-2 text-sm text-stone-600">
          Your papers:
          {papers.map((p, i) => (
            <button
              key={p.id}
              onClick={() => setOpenId(p.id)}
              className={`rounded-full px-3 py-1 ${
                p.id === paper?.id ? "bg-stone-800 text-white" : "border border-stone-300 hover:bg-stone-100"
              }`}
            >
              {p.total_marks} marks #{papers.length - i}
            </button>
          ))}
        </div>
      )}

      {paper && (
        <div className="mt-6">
          <div className="no-print mb-3 flex flex-wrap items-center justify-between gap-3">
            <label className="flex items-center gap-2 text-sm text-stone-600">
              <input type="checkbox" checked={showAnswers} onChange={(e) => setShowAnswers(e.target.checked)} />
              Show answers and marking scheme
            </label>
            <div className="flex gap-2">
              <button onClick={() => window.print()} className={secondaryButton}>
                Print / save as PDF
              </button>
              <button onClick={() => remove(paper)} className={secondaryButton}>
                Delete
              </button>
            </div>
          </div>
          <PaperView paper={paper} showAnswers={showAnswers} subject={set.subject} />
        </div>
      )}
    </div>
  );
}

function PaperView({ paper, showAnswers, subject }: { paper: Paper; showAnswers: boolean; subject: string }) {
  return (
    <article className="print-area rounded-xl border border-stone-200 bg-white p-8 shadow-sm print:border-0 print:p-0 print:shadow-none">
      <header className="border-b border-stone-300 pb-4 text-center">
        <h2 className="text-xl font-semibold text-stone-900">{paper.title}</h2>
        {subject && <p className="mt-1 text-sm text-stone-600">{subject}</p>}
        <p className="mt-2 flex justify-between text-sm text-stone-700">
          <span>{paper.duration_minutes ? `Time: ${paper.duration_minutes} minutes` : ""}</span>
          <span>Total marks: {paper.total_marks}</span>
        </p>
      </header>

      {paper.instructions.length > 0 && (
        <div className="mt-4 text-sm text-stone-700">
          <p className="font-medium">Instructions</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-5">
            {paper.instructions.map((x, i) => (
              <li key={i}>{x}</li>
            ))}
          </ul>
        </div>
      )}

      {paper.sections.map((s, i) => (
        <section key={i} className="mt-6">
          <h3 className="text-base font-semibold text-stone-900">{s.name}</h3>
          {s.instructions && <p className="text-sm italic text-stone-600">{s.instructions}</p>}
          <ol className="mt-3 space-y-4">
            {s.questions.map((q) => (
              <li key={q.number} className="break-inside-avoid text-sm text-stone-800">
                <p className="flex justify-between gap-4">
                  <span>
                    <span className="font-medium">{q.number}.</span> {q.question}
                  </span>
                  <span className="shrink-0 text-stone-600">[{q.marks}]</span>
                </p>
                {q.options.length > 0 && (
                  <ul className="mt-1 grid gap-x-6 pl-5 sm:grid-cols-2">
                    {q.options.map((o, j) => (
                      <li key={j}>
                        ({String.fromCharCode(97 + j)}) {o}
                      </li>
                    ))}
                  </ul>
                )}
                {showAnswers && (
                  <div className="mt-2 rounded-lg bg-emerald-50 px-3 py-2 text-emerald-900">
                    <p>
                      <span className="font-medium">Answer: </span>
                      {q.answer}
                    </p>
                    {q.marking_scheme && (
                      <p className="mt-1 text-emerald-800/80">
                        <span className="font-medium">Marking: </span>
                        {q.marking_scheme}
                      </p>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ol>
        </section>
      ))}
    </article>
  );
}
