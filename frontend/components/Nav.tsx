"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/components/AuthProvider";

const links = [
  { href: "/", label: "New set", match: (p: string) => p === "/" },
  { href: "/sets", label: "My sets", match: (p: string) => p.startsWith("/sets") },
  { href: "/flashcards/review", label: "Flashcards", match: (p: string) => p.startsWith("/flashcards") },
];

export default function Nav() {
  const pathname = usePathname();
  const { user, logout } = useAuth();

  return (
    <header className="no-print border-b border-stone-200 bg-white/70 backdrop-blur">
      <nav className="mx-auto flex max-w-4xl flex-wrap items-center justify-between gap-2 px-6 py-4">
        <span className="font-medium tracking-tight text-stone-800">Study Guide</span>
        {user ? (
          <div className="flex flex-wrap items-center gap-3">
            <ul className="flex gap-1">
              {links.map(({ href, label, match }) => {
                const active = match(pathname);
                return (
                  <li key={href}>
                    <Link
                      href={href}
                      className={`rounded-full px-4 py-1.5 text-sm transition-colors ${
                        active ? "bg-teal-700 text-white" : "text-stone-600 hover:bg-stone-100"
                      }`}
                    >
                      {label}
                    </Link>
                  </li>
                );
              })}
            </ul>
            <span className="hidden text-xs text-stone-400 sm:inline">{user.email}</span>
            <button onClick={logout} className="rounded-full px-3 py-1.5 text-sm text-stone-500 hover:bg-stone-100">
              Log out
            </button>
          </div>
        ) : (
          <div className="flex gap-1 text-sm">
            <Link href="/login" className="rounded-full px-4 py-1.5 text-stone-600 hover:bg-stone-100">
              Log in
            </Link>
            <Link href="/signup" className="rounded-full bg-teal-700 px-4 py-1.5 text-white hover:bg-teal-800">
              Sign up
            </Link>
          </div>
        )}
      </nav>
    </header>
  );
}
