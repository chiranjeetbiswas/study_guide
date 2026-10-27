"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/components/AuthProvider";
import type { User } from "@/lib/api";

const links = [
  { href: "/", label: "New set", match: (p: string) => p === "/" },
  { href: "/sets", label: "My sets", match: (p: string) => p.startsWith("/sets") },
  { href: "/flashcards/review", label: "Flashcards", match: (p: string) => p.startsWith("/flashcards") },
];

function ProfileMenu({ user, logout }: { user: User; logout: () => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  // Accounts made before names were asked for have none, so fall back to the start of the email
  const name = user.name || user.email.split("@")[0];
  const initial = name.charAt(0).toUpperCase();
  const since = user.created_at
    ? new Date(user.created_at).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })
    : null;

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-label="Profile"
        aria-expanded={open}
        className="flex h-9 w-9 items-center justify-center rounded-full bg-teal-700 text-sm font-medium text-white hover:bg-teal-800"
      >
        {initial}
      </button>
      {open && (
        <div className="absolute right-0 z-10 mt-2 w-64 rounded-xl border border-stone-200 bg-white p-4 shadow-lg">
          <div className="flex items-center gap-3">
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-teal-700 text-lg font-medium text-white">
              {initial}
            </span>
            <div className="min-w-0">
              <p className="truncate font-medium text-stone-800">{name}</p>
              <p className="truncate text-xs text-stone-500">{user.email}</p>
            </div>
          </div>
          {since && <p className="mt-3 text-xs text-stone-400">Member since {since}</p>}
          <button
            onClick={logout}
            className="mt-4 w-full rounded-full border border-stone-200 px-4 py-2 text-sm text-stone-600 hover:bg-stone-100"
          >
            Log out
          </button>
        </div>
      )}
    </div>
  );
}

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
            <ProfileMenu user={user} logout={logout} />
          </div>
        ) : (
          <div className="flex gap-1 text-sm">
            {[
              { href: "/login", label: "Log in" },
              { href: "/signup", label: "Sign up" },
            ].map(({ href, label }) => (
              <Link
                key={href}
                href={href}
                className={`rounded-full px-4 py-1.5 transition-colors ${
                  pathname === href ? "bg-teal-700 text-white" : "text-stone-600 hover:bg-stone-100"
                }`}
              >
                {label}
              </Link>
            ))}
          </div>
        )}
      </nav>
    </header>
  );
}
