"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";

const MAX_FILE_BYTES = 5 * 1024 * 1024; // matches the backend limit

const field =
  "w-full rounded-lg border border-stone-200 bg-white px-3 py-2 text-sm text-stone-800 outline-none placeholder:text-stone-400 focus:border-teal-600 focus:ring-2 focus:ring-teal-600/20";

export default function NewSetPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"paste" | "upload">("paste");
  const [notes, setNotes] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [subject, setSubject] = useState("");
  const [level, setLevel] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    const details = { title: "", subject, level };
    try {
      const set = mode === "paste" ? await api.createSet(notes, details) : await api.createSetFromFile(file!, details);
      router.push(`/sets/${set.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
      setLoading(false);
    }
  }

  function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const picked = e.target.files?.[0] ?? null;
    if (picked && picked.size > MAX_FILE_BYTES) {
      setFile(null);
      setError("That file is larger than 5 MB.");
      return;
    }
    setError(null);
    setFile(picked);
  }

  const notReady = mode === "paste" ? notes.trim().length < 20 : file === null;

  const tab = (active: boolean) =>
    `rounded-full px-4 py-1.5 text-sm transition-colors ${
      active ? "bg-stone-800 text-white" : "text-stone-600 hover:bg-stone-100"
    }`;

  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight text-stone-800">Prepare for your exam</h1>
      <p className="mt-2 text-stone-600">
        Add your notes once. Then get easy revision notes, a practice quiz, an exam paper for any number of marks, and
        flashcards.
      </p>

      <div className="mt-6 flex gap-1">
        <button type="button" onClick={() => setMode("paste")} className={tab(mode === "paste")}>
          Paste text
        </button>
        <button type="button" onClick={() => setMode("upload")} className={tab(mode === "upload")}>
          Upload file
        </button>
      </div>

      <form onSubmit={handleCreate} className="mt-4 space-y-4">
        {mode === "paste" ? (
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Paste your notes here…"
            rows={12}
            className="w-full rounded-xl border border-stone-200 bg-white p-4 text-stone-800 shadow-sm outline-none placeholder:text-stone-400 focus:border-teal-600 focus:ring-2 focus:ring-teal-600/20"
          />
        ) : (
          <label className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-stone-300 bg-white p-10 text-center text-stone-600 hover:border-teal-600">
            <span className="font-medium text-stone-800">{file ? file.name : "Choose a .pdf or .txt file"}</span>
            <span className="text-xs text-stone-400">
              Up to 5 MB. PDFs need selectable text; scanned images aren’t supported.
            </span>
            <input type="file" accept=".pdf,.txt,application/pdf,text/plain" onChange={handleFile} className="sr-only" />
          </label>
        )}

        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-sm text-stone-600">
            Subject <span className="text-stone-400">(optional)</span>
            <input value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="e.g. Biology" className={`mt-1 ${field}`} />
          </label>
          <label className="text-sm text-stone-600">
            Your level <span className="text-stone-400">(optional)</span>
            <input value={level} onChange={(e) => setLevel(e.target.value)} placeholder="e.g. Class 10, first-year college" className={`mt-1 ${field}`} />
          </label>
        </div>

        <div className="flex justify-end">
          <button
            type="submit"
            disabled={loading || notReady}
            className="rounded-full bg-teal-700 px-6 py-2.5 text-sm font-medium text-white transition-colors hover:bg-teal-800 disabled:cursor-not-allowed disabled:bg-stone-300"
          >
            {loading ? "Saving…" : "Continue"}
          </button>
        </div>
      </form>

      {error && (
        <p role="alert" className="mt-6 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
          {error}
        </p>
      )}
    </div>
  );
}
