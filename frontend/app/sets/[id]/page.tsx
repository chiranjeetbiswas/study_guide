"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import FlashcardsTab from "@/components/set/FlashcardsTab";
import PaperTab from "@/components/set/PaperTab";
import QuizTab from "@/components/set/QuizTab";
import RevisionTab from "@/components/set/RevisionTab";
import { api, type StudySet } from "@/lib/api";

const TABS = ["Revision notes", "Quiz", "Exam paper", "Flashcards"] as const;
type TabName = (typeof TABS)[number];

export default function SetPage() {
  const { id } = useParams<{ id: string }>();
  const [set, setSet] = useState<StudySet | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<TabName>("Revision notes");

  useEffect(() => {
    api
      .getSet(id)
      .then(setSet)
      .catch((err) => setError(err instanceof Error ? err.message : "Something went wrong"));
  }, [id]);

  if (error) {
    return (
      <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
        {error}{" "}
        <Link href="/sets" className="font-medium underline">
          Back to my sets
        </Link>
      </p>
    );
  }
  if (!set) return <p className="text-stone-500">Loading…</p>;

  return (
    <div>
      <div className="no-print">
        <Link href="/sets" className="text-sm text-stone-500 hover:text-stone-800">
          ← My sets
        </Link>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight text-stone-800">{set.title}</h1>
        {set.level && <p className="mt-1 text-sm text-stone-500">{set.level}</p>}

        <ul className="mt-6 flex flex-wrap gap-1 border-b border-stone-200 pb-3">
          {TABS.map((name) => (
            <li key={name}>
              <button
                onClick={() => setTab(name)}
                className={`rounded-full px-4 py-1.5 text-sm transition-colors ${
                  tab === name ? "bg-teal-700 text-white" : "text-stone-600 hover:bg-stone-100"
                }`}
              >
                {name}
              </button>
            </li>
          ))}
        </ul>
      </div>

      <div className="mt-6">
        {tab === "Revision notes" && <RevisionTab set={set} onChange={setSet} />}
        {tab === "Quiz" && <QuizTab set={set} onChange={setSet} />}
        {tab === "Exam paper" && <PaperTab set={set} onChange={setSet} />}
        {tab === "Flashcards" && <FlashcardsTab set={set} onChange={setSet} />}
      </div>
    </div>
  );
}
