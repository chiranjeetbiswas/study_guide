"use client";

import Link from "next/link";
import { useState } from "react";
import { useAuth } from "@/components/AuthProvider";

export default function AuthForm({ mode }: { mode: "login" | "signup" }) {
  const { login, signup } = useAuth();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isSignup = mode === "signup";

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await (isSignup ? signup(name.trim(), email, password) : login(email, password));
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
        {isSignup && (
          <label className="block text-sm text-stone-600">
            Name
            <input
              type="text"
              required
              maxLength={60}
              autoComplete="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className={input}
            />
          </label>
        )}
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
          <div className="relative">
            <input
              type={showPassword ? "text" : "password"}
              required
              minLength={isSignup ? 8 : undefined}
              maxLength={128}
              autoComplete={isSignup ? "new-password" : "current-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={`${input} pr-11`}
            />
            <button
              type="button"
              onClick={() => setShowPassword((s) => !s)}
              aria-label={showPassword ? "Hide password" : "Show password"}
              aria-pressed={showPassword}
              className="absolute inset-y-0 right-0 mt-1 flex items-center px-3 text-stone-400 hover:text-stone-600"
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="h-5 w-5"
                aria-hidden="true"
              >
                {showPassword ? (
                  <>
                    <path d="M3 3l18 18" />
                    <path d="M10.6 6.1A9.8 9.8 0 0 1 12 6c5 0 8.5 4 9.5 6a12.7 12.7 0 0 1-2.7 3.4M6.5 7.6A12.6 12.6 0 0 0 2.5 12c1 2 4.5 6 9.5 6 1.5 0 2.8-.4 4-.9" />
                    <path d="M9.9 9.9a3 3 0 0 0 4.2 4.2" />
                  </>
                ) : (
                  <>
                    <path d="M2.5 12C3.5 10 7 6 12 6s8.5 4 9.5 6c-1 2-4.5 6-9.5 6s-8.5-4-9.5-6z" />
                    <circle cx="12" cy="12" r="3" />
                  </>
                )}
              </svg>
            </button>
          </div>
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
