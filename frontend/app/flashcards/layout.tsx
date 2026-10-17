"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const tabs = [
  { href: "/flashcards/review", label: "Review queue" },
  { href: "/flashcards/library", label: "Library" },
  { href: "/flashcards/due", label: "Due today" },
  { href: "/flashcards/quiz", label: "Practice" },
];

export default function FlashcardsLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return (
    <div>
      <ul className="mb-8 flex flex-wrap gap-1 border-b border-stone-200 pb-3">
        {tabs.map(({ href, label }) => (
          <li key={href}>
            <Link
              href={href}
              className={`rounded-full px-4 py-1.5 text-sm transition-colors ${
                pathname === href ? "bg-stone-800 text-white" : "text-stone-600 hover:bg-stone-100"
              }`}
            >
              {label}
            </Link>
          </li>
        ))}
      </ul>
      {children}
    </div>
  );
}
