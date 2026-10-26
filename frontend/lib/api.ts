// Base URL of the FastAPI backend. Override with NEXT_PUBLIC_API_URL in frontend/.env.local
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type CardStatus = "pending" | "approved" | "rejected";

export type Card = {
  id: string;
  note_id: string;
  question: string;
  answer: string;
  source: string;
  status: CardStatus;
  created_at: string;
  ease_factor: number;
  interval_days: number;
  repetitions: number;
  due_date: string | null; // YYYY-MM-DD, null = never reviewed
  check_status: "supported" | "flagged" | null; // null = never checked
  check_reason: string | null;
};

export type CheckStats = {
  checked: number;
  supported: number;
  flagged: number;
  flagged_rate: number; // 0-1
};

export type GenerateResult = {
  note_id: string;
  cards: Card[];
  dropped: number;
};

export type User = { id: string; email: string };

export type StudySetSummary = {
  id: string;
  title: string;
  subject: string;
  level: string;
  created_at: string;
  chars: number;
  has_revision: boolean;
  has_quiz: boolean;
  paper_count: number;
  card_count: number;
};

export type Topic = {
  title: string;
  explanation: string;
  key_points: string[];
  terms: { term: string; meaning: string }[];
  likely_questions: string[];
};

export type QuizQuestion = { question: string; options: string[]; answer_index: number; explanation: string };

export type PaperQuestion = {
  number: number;
  question: string;
  marks: number;
  options: string[];
  answer: string;
  marking_scheme: string;
};

export type Paper = {
  id: string;
  created_at: string;
  title: string;
  total_marks: number;
  duration_minutes: number | null;
  instructions: string[];
  sections: { name: string; instructions: string; questions: PaperQuestion[] }[];
};

export type StudySet = StudySetSummary & {
  revision: Topic[] | null;
  quiz: QuizQuestion[] | null;
  papers: Paper[];
};

export type AskSource = {
  number: number; // the [n] used in the answer
  chunk_index: number;
  page_number: number | null;
  heading: string | null;
  snippet: string;
  text: string;
  score: number;
};
export type AskResult = { found: boolean; answer: string; sources: AskSource[] };

export type SetDetails ={ title: string; subject: string; level: string };

// The login token lives in localStorage so it survives a refresh. Trade-off: any script running on
// the page (e.g. from an XSS bug) could read it. httpOnly cookies avoid that but need CSRF handling.
const TOKEN_KEY = "study_guide_token";

export const tokenStore = {
  get(): string | null {
    try {
      return localStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set(token: string) {
    try {
      localStorage.setItem(TOKEN_KEY, token);
    } catch {}
  },
  clear() {
    try {
      localStorage.removeItem(TOKEN_KEY);
    } catch {}
  },
};

async function request<T>(path: string, init?: RequestInit, { auth = true } = {}): Promise<T> {
  const headers = new Headers(init?.headers);
  // JSON bodies are strings; FormData and URLSearchParams set their own content type
  if (typeof init?.body === "string" && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const token = auth ? tokenStore.get() : null;
  if (token) headers.set("Authorization", `Bearer ${token}`);

  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { ...init, headers });
  } catch {
    throw new Error("Can't reach the server. Is the backend running on " + API_URL + "?");
  }

  if (!res.ok) {
    // Expired or invalid token: drop it and send the user to log in again
    if (res.status === 401 && token) {
      tokenStore.clear();
      // Full reload on purpose (not the router): wipes any stale per-user page state
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.href = "/login";
    }
    let message = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      // FastAPI sends {detail: "text"} for our errors and {detail: [...]} for validation errors
      if (typeof body.detail === "string") message = body.detail;
      else if (Array.isArray(body.detail)) message = body.detail.map((d: { msg: string }) => d.msg).join(", ");
    } catch {}
    throw new Error(message);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

type Token = { access_token: string; token_type: string };

export const api = {
  signup: (email: string, password: string) =>
    request<Token>("/auth/signup", { method: "POST", body: JSON.stringify({ email, password }) }, { auth: false }),
  // The backend's login takes form fields (OAuth2 standard), with the email in "username"
  login: (email: string, password: string) =>
    request<Token>(
      "/auth/login",
      { method: "POST", body: new URLSearchParams({ username: email, password }) },
      { auth: false },
    ),
  me: () => request<User>("/auth/me"),

  generate: (notes: string, maxCards: number) =>
    request<GenerateResult>("/flashcards", {
      method: "POST",
      body: JSON.stringify({ notes, max_cards: maxCards }),
    }),
  upload: (file: File, maxCards: number) => {
    const form = new FormData();
    form.append("file", file);
    form.append("max_cards", String(maxCards));
    return request<GenerateResult>("/flashcards/upload", { method: "POST", body: form });
  },
  listSets: () => request<StudySetSummary[]>("/sets"),
  getSet: (id: string) => request<StudySet>(`/sets/${id}`),
  createSet: (notes: string, d: SetDetails) => request<StudySet>("/sets", { method: "POST", body: JSON.stringify({ notes, ...d }) }),
  createSetFromFile: (file: File, d: SetDetails) => {
    const form = new FormData();
    form.append("file", file);
    form.append("title", d.title);
    form.append("subject", d.subject);
    form.append("level", d.level);
    return request<StudySet>("/sets/upload", { method: "POST", body: form });
  },
  deleteSet: (id: string) => request<void>(`/sets/${id}`, { method: "DELETE" }),
  makeRevision: (id: string) => request<StudySet>(`/sets/${id}/revision`, { method: "POST" }),
  makeQuiz: (id: string, count: number) =>
    request<StudySet>(`/sets/${id}/quiz`, { method: "POST", body: JSON.stringify({ count }) }),
  makePaper: (id: string, body: { total_marks: number; duration_minutes: number | null; details: string }) =>
    request<StudySet>(`/sets/${id}/paper`, { method: "POST", body: JSON.stringify(body) }),
  deletePaper: (id: string, paperId: string) => request<StudySet>(`/sets/${id}/paper/${paperId}`, { method: "DELETE" }),
  makeSetFlashcards: (id: string, maxCards: number) =>
    request<GenerateResult>(`/sets/${id}/flashcards`, { method: "POST", body: JSON.stringify({ max_cards: maxCards }) }),
  askSet: (id: string, question: string) =>
    request<AskResult>(`/sets/${id}/ask`, { method: "POST", body: JSON.stringify({ question }) }),
  listCards: (status: CardStatus) => request<Card[]>(`/cards?status=${status}`),
  checkStats: () => request<CheckStats>("/stats/checks"),
  dueCards: () => request<Card[]>("/quiz/due"),
  review: (id: string, knew: boolean) =>
    request<Card>(`/cards/${id}/review`, { method: "POST", body: JSON.stringify({ knew }) }),
  approve: (id: string) => request<Card>(`/cards/${id}/approve`, { method: "POST" }),
  reject: (id: string) => request<Card>(`/cards/${id}/reject`, { method: "POST" }),
  edit: (id: string, fields: { question?: string; answer?: string }) =>
    request<Card>(`/cards/${id}`, { method: "PATCH", body: JSON.stringify(fields) }),
};
