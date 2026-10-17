import type { ReactNode } from "react";

export const primaryButton =
  "rounded-full bg-teal-700 px-6 py-2.5 text-sm font-medium text-white transition-colors hover:bg-teal-800 disabled:cursor-not-allowed disabled:bg-stone-300";

export const secondaryButton =
  "rounded-full border border-stone-300 px-4 py-1.5 text-sm text-stone-700 transition-colors hover:bg-stone-100 disabled:cursor-not-allowed disabled:opacity-50";

export const inputClass =
  "rounded-lg border border-stone-200 bg-white px-3 py-2 text-sm text-stone-800 outline-none placeholder:text-stone-400 focus:border-teal-600 focus:ring-2 focus:ring-teal-600/20";

export function ErrorBox({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p role="alert" className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
      {message}
    </p>
  );
}

export function EmptyState({ title, text, children }: { title: string; text: string; children: ReactNode }) {
  return (
    <div className="rounded-2xl border border-dashed border-stone-300 p-10 text-center">
      <p className="font-medium text-stone-800">{title}</p>
      <p className="mx-auto mt-2 max-w-md text-sm text-stone-500">{text}</p>
      <div className="mt-5 flex flex-wrap items-center justify-center gap-3">{children}</div>
    </div>
  );
}

export function errorMessage(err: unknown) {
  return err instanceof Error ? err.message : "Something went wrong";
}
