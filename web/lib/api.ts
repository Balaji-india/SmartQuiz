// One function per endpoint. Always the real API: mock data lives only in tests.
import type {
  AttemptResult,
  AuthOut,
  ChatOut,
  DocumentOut,
  MetricsOut,
  QuizOut,
  QuizProgressOut,
  TextbookOut,
  User,
  VerifyFactOut,
  VerifyQuestionOut,
  VerifyQuizOut,
} from "./types";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const TOKEN_KEY = "smartquiz_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    // Storage blocked: the session simply does not persist.
  }
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

function detailText(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length && typeof detail[0]?.msg === "string") return detail[0].msg;
  return fallback;
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "Cannot reach the SmartQuiz API. Is it running?");
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    if (response.status === 401 && token) setToken(null);
    throw new ApiError(response.status, detailText(body?.detail, response.statusText || "Request failed"));
  }
  return response.json() as Promise<T>;
}

const post = <T>(path: string, body?: unknown) =>
  apiFetch<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export type Health = { ok: boolean; db: boolean };
export const getHealth = () => apiFetch<Health>("/health");

// Auth
export const signup = (email: string, password: string, name: string) => post<AuthOut>("/auth/signup", { email, password, name });
export const login = (email: string, password: string) => post<AuthOut>("/auth/login", { email, password });
export const getMe = () => apiFetch<User>("/auth/me");

// Documents
export function uploadDocument(file: File): Promise<DocumentOut> {
  const form = new FormData();
  form.append("file", file);
  return apiFetch<DocumentOut>("/documents", { method: "POST", body: form });
}
export const listDocuments = () => apiFetch<DocumentOut[]>("/documents");
export const getDocument = (id: string) => apiFetch<DocumentOut>(`/documents/${id}`);
export const getTextbook = (id: string) => apiFetch<TextbookOut>(`/documents/${id}/textbook`);
export const registerDocument = (id: string) => post<DocumentOut>(`/documents/${id}/register`);

// Quizzes
export const createQuiz = (document_id: string, num_questions = 10, time_limit_sec = 600) =>
  post<QuizOut>("/quizzes", { document_id, num_questions, time_limit_sec });
export const getQuiz = (id: string) => apiFetch<QuizOut>(`/quizzes/${id}`);
export const getQuizProgress = (id: string) => apiFetch<QuizProgressOut>(`/quizzes/${id}/progress`);
export const startQuiz = (id: string) => post<QuizOut>(`/quizzes/${id}/start`);
export const submitAttempt = (id: string, answers: (number | null)[], time_taken_sec: number) =>
  post<AttemptResult>(`/quizzes/${id}/attempts`, { answers, time_taken_sec });

// Chat and metrics
export const sendChat = (document_id: string, message: string) => post<ChatOut>("/chat", { document_id, message });
export const getMetrics = (document_id: string) => apiFetch<MetricsOut>(`/metrics/${document_id}`);

// Public verify
export const verifyQuestion = (id: string) => apiFetch<VerifyQuestionOut>(`/verify/question/${id}`);
export const verifyFact = (document_id: string, idx: number, text: string) =>
  post<VerifyFactOut>("/verify/fact", { document_id, idx, text });
export const verifyQuiz = (id: string) => apiFetch<VerifyQuizOut>(`/verify/quiz/${id}`);
