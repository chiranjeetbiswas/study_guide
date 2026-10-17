"use client";

import Link from "next/link";
import { useState } from "react";
import { useAuth } from "@/components/AuthProvider";

export default function AuthForm({ mode }: { mode: "login" | "signup" }) {
  const { login, signup } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isSignup = mode === "signup";

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await (isSignup ? signup : login)(email, password);
      // AuthProvider redirects to the home page once the user is set
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
      setBusy(false);
    }
  }

  const input =
    "mt-1 w-full rounded-lg border border-stone-200 bg-white px-3 py-2.5 text-stone-800 outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-600/20";

  return (
    <div className="mx-auto mt-6 max-w-sm">
      <h1 className="text-2xl font-semibold tracking-tight text-stone-800">
        {isSignup ? "Create your account" : "Welcome back"}
      </h1>
      <p className="mt-2 text-stone-600">
        {isSignup ? "Your notes and cards stay private to you." : "Log in to see your cards."}
      </p>

      <form onSubmit={handleSubmit} className="mt-8 space-y-4">
        <label className="block text-sm text-stone-600">
          Email
          <input
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className={input}
          />
        </label>
        <label className="block text-sm text-stone-600">
          Password
          <input
            type="password"
            required
            minLength={isSignup ? 8 : undefined}
            maxLength={128}
            autoComplete={isSignup ? "new-password" : "current-password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={input}
          />
          {isSignup && <span className="mt-1 block text-xs text-stone-400">At least 8 characters.</span>}
        </label>

        {error && (
          <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-full bg-teal-700 px-6 py-2.5 text-sm font-medium text-white hover:bg-teal-800 disabled:bg-stone-300"
        >
          {busy ? "Please wait…" : isSignup ? "Sign up" : "Log in"}
        </button>
      </form>

      <p className="mt-6 text-center text-sm text-stone-500">
        {isSignup ? "Already have an account?" : "New here?"}{" "}
        <Link href={isSignup ? "/login" : "/signup"} className="font-medium text-teal-700 underline underline-offset-2">
          {isSignup ? "Log in" : "Create an account"}
        </Link>
      </p>
    </div>
  );
}
