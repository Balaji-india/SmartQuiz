"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { useLoad } from "@/lib/use-load";
import { AuthedPage } from "@/components/shell";
import { Button, ButtonLink, Card, ChainBadge, ErrorBox, Hash, Loading, NavyPanel } from "@/components/ui";
import { createQuiz, getQuiz, getQuizProgress, startQuiz, submitAttempt } from "@/lib/api";
import type { AttemptResult, QuizOut, QuizProgressOut } from "@/lib/types";

const POLL_MS = 2000;
const LETTERS = ["A", "B", "C", "D"];

// Per-tab conveniences only: the server is the source of truth for timing and scoring.
function stored<T>(key: string): T | null {
  try {
    const raw = window.sessionStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}
function store(key: string, value: unknown) {
  try {
    window.sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    // ignore
  }
}

function progressText(p: QuizProgressOut | null): string {
  if (!p) return "Preparing your quiz…";
  const rejected = p.rejected ? ` · ${p.rejected} rejected so far` : "";
  switch (p.stage) {
    case "selecting":
      return "Choosing facts you have not been tested on…";
    case "generating":
      return `Writing questions from your facts${rejected}`;
    case "verifying":
      return `Verifying question ${Math.min(p.accepted + 1, p.target)} of ${p.target}${rejected}`;
    case "committing":
      return "Committing the quiz hash on chain…";
    default:
      return "Finishing…";
  }
}

function Generating({ id, onDone }: { id: string; onDone: () => void }) {
  const [p, setP] = useState<QuizProgressOut | null>(null);
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const next = await getQuizProgress(id);
        if (!alive) return;
        setP(next);
        if (next.stage === "done" || next.stage === "failed") onDone();
      } catch {
        // keep polling; a transient error should not end the screen
      }
    };
    tick();
    const timer = setInterval(tick, POLL_MS);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [id, onDone]);
  const pct = p && p.target ? Math.round((100 * p.accepted) / p.target) : 0;
  return (
    <NavyPanel className="mx-auto max-w-2xl">
      <p className="text-xs font-semibold uppercase tracking-widest text-accent">Building a verified quiz</p>
      <h1 className="mt-2 text-2xl font-semibold">{progressText(p)}</h1>
      <div className="mt-6 h-3 overflow-hidden rounded-full bg-white/10" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
        <div className="h-full rounded-full bg-accent transition-all duration-500" style={{ width: `${pct}%` }} />
      </div>
      <p className="mt-3 text-sm text-white/70">
        {p ? `${p.accepted} accepted · ${p.rejected} rejected by the checks` : "Starting…"} — every question must pass grounding and solvability
        checks by an independent model before it reaches you. The timer has not started.
      </p>
    </NavyPanel>
  );
}

function StartScreen({ quiz, onBegin, busy }: { quiz: QuizOut; onBegin: () => void; busy: boolean }) {
  const count = quiz.generation?.accepted ?? 0;
  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <NavyPanel>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <p className="text-xs font-semibold uppercase tracking-widest text-accent">Ready</p>
          <ChainBadge status={quiz.chain_status} />
        </div>
        <h1 className="mt-2 text-3xl font-semibold">
          {count} questions · {Math.round(quiz.time_limit_sec / 60)} minutes
        </h1>
        <p className="mt-3 text-white/75">
          This quiz was sealed before you see it: its hash is committed on chain, so nobody can change a question or an answer afterwards.
        </p>
        <div className="mt-5 flex flex-col gap-2 border-t border-white/10 pt-4 sm:flex-row sm:flex-wrap sm:items-center sm:gap-4">
          {quiz.quiz_hash && <Hash value={quiz.quiz_hash} label="Quiz hash" dark />}
          {quiz.explorer_url && (
            <a href={quiz.explorer_url} target="_blank" rel="noreferrer" className="text-sm font-semibold text-accent underline underline-offset-2 hover:text-white">
              Commit transaction ↗
            </a>
          )}
        </div>
        {quiz.generation && (
          <p className="mt-3 text-sm text-white/60">
            {quiz.generation.candidates} candidates written, {quiz.generation.rejected} rejected by the checks.
          </p>
        )}
      </NavyPanel>
      <Button onClick={onBegin} disabled={busy || count === 0} className="w-full text-base">
        {busy ? "Starting…" : "Begin — the timer starts now"}
      </Button>
    </div>
  );
}

/** Seconds left; calls onExpire once when it reaches 0 (auto-submit at 0:00). */
function useCountdown(startedAt: string, limitSec: number, onExpire: () => void): number {
  const end = new Date(startedAt).getTime() + limitSec * 1000;
  const [left, setLeft] = useState(() => Math.max(0, Math.round((end - Date.now()) / 1000)));
  const expire = useRef(onExpire);
  useEffect(() => {
    expire.current = onExpire;
  }, [onExpire]);
  useEffect(() => {
    let fired = false;
    const timer = setInterval(() => {
      const next = Math.max(0, Math.round((end - Date.now()) / 1000));
      setLeft(next);
      if (next === 0 && !fired) {
        fired = true;
        expire.current();
      }
    }, 500);
    return () => clearInterval(timer);
  }, [end]);
  return left;
}

function Taking({ quiz, onSubmitted }: { quiz: QuizOut; onSubmitted: (r: AttemptResult) => void }) {
  const key = `sq_answers_${quiz.id}`;
  const questions = quiz.questions;
  const [answers, setAnswers] = useState<(number | null)[]>(() => stored<(number | null)[]>(key) ?? questions.map(() => null));
  const [current, setCurrent] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submitted = useRef(false);

  const submit = useCallback(async () => {
    if (submitted.current) return;
    submitted.current = true;
    setBusy(true);
    setError(null);
    try {
      const elapsed = Math.round((Date.now() - new Date(quiz.started_at!).getTime()) / 1000);
      const result = await submitAttempt(quiz.id, answers, Math.max(0, elapsed));
      store(`sq_result_${quiz.id}`, result);
      onSubmitted(result);
    } catch (e) {
      submitted.current = false;
      setError((e as Error).message);
      setBusy(false);
    }
  }, [answers, onSubmitted, quiz.id, quiz.started_at]);
  const left = useCountdown(quiz.started_at!, quiz.time_limit_sec, submit);

  const choose = (i: number) => {
    const next = answers.map((a, k) => (k === current ? i : a));
    setAnswers(next);
    store(key, next);
  };

  const q = questions[current];
  const answered = answers.filter((a) => a !== null).length;
  const mm = String(Math.floor(left / 60)).padStart(1, "0");
  const ss = String(left % 60).padStart(2, "0");
  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-muted">
          Question {current + 1} of {questions.length} · {answered} answered
        </p>
        <p className={`rounded-lg px-3 py-1.5 font-mono text-lg font-semibold ${left <= 60 ? "bg-bad-soft text-bad" : "bg-navy text-white"}`} aria-live="polite">
          {mm}:{ss}
        </p>
      </div>
      <div className="flex flex-wrap gap-1.5" aria-label="Questions">
        {questions.map((item, k) => (
          <button
            key={item.id}
            onClick={() => setCurrent(k)}
            aria-label={`Question ${k + 1}${answers[k] !== null ? ", answered" : ""}`}
            className={`h-3 w-7 rounded-full ${k === current ? "bg-accent" : answers[k] !== null ? "bg-navy" : "bg-line"}`}
          />
        ))}
      </div>
      <Card>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="rounded-full bg-paper px-2.5 py-1 font-semibold capitalize text-muted">{q.bloom_level}</span>
          {q.flagged_general && (
            <span className="rounded-full bg-warn-soft px-2.5 py-1 font-semibold text-warn" title="An independent model could often answer this without your notes">
              General knowledge
            </span>
          )}
        </div>
        <h2 className="mt-3 text-xl font-semibold leading-snug">{q.stem}</h2>
        <ul className="mt-5 space-y-2.5">
          {q.options.map((option, i) => (
            <li key={i}>
              <button
                onClick={() => choose(i)}
                aria-pressed={answers[current] === i}
                className={`flex w-full items-start gap-3 rounded-lg border px-4 py-3 text-left transition-colors ${answers[current] === i ? "border-accent bg-warn-soft" : "border-line hover:border-ink"}`}
              >
                <span className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold ${answers[current] === i ? "bg-accent text-navy" : "bg-paper text-muted"}`}>
                  {LETTERS[i]}
                </span>
                <span>{option}</span>
              </button>
            </li>
          ))}
        </ul>
      </Card>
      {error && <ErrorBox message={error} />}
      <div className="flex flex-wrap justify-between gap-3">
        <Button variant="ghost" onClick={() => setCurrent((c) => Math.max(0, c - 1))} disabled={current === 0}>
          ← Previous
        </Button>
        {current < questions.length - 1 ? (
          <Button variant="secondary" onClick={() => setCurrent((c) => c + 1)}>
            Next →
          </Button>
        ) : (
          <Button onClick={submit} disabled={busy}>
            {busy ? "Submitting…" : `Submit (${answered}/${questions.length} answered)`}
          </Button>
        )}
      </div>
    </div>
  );
}

function Results({ quiz, result }: { quiz: QuizOut; result: AttemptResult | null }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const byId = new Map(result?.results.map((r) => [r.question_id, r]));

  const newQuiz = async () => {
    setBusy(true);
    setError(null);
    try {
      const next = await createQuiz(quiz.document_id, 10, 600);
      router.push(`/quiz/${next.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <NavyPanel>
        <p className="text-xs font-semibold uppercase tracking-widest text-accent">Results</p>
        {result ? (
          <h1 className="mt-2 text-4xl font-semibold">
            {result.score} <span className="text-white/50">/ {result.total}</span>
          </h1>
        ) : (
          <h1 className="mt-2 text-2xl font-semibold">This quiz has been submitted.</h1>
        )}
        <div className="mt-5 flex flex-wrap gap-3">
          <Button onClick={newQuiz} disabled={busy}>
            {busy ? "Creating…" : "New quiz (no repeats)"}
          </Button>
          <Link href={`/verify?quiz=${quiz.id}`} className="inline-flex min-h-11 items-center rounded-lg border border-white/25 px-4 py-2 text-sm font-semibold text-white hover:border-white">
            Verify this quiz
          </Link>
          <Link href={`/documents/${quiz.document_id}`} className="inline-flex min-h-11 items-center px-2 text-sm font-semibold text-white/75 hover:text-white">
            Back to textbook
          </Link>
        </div>
      </NavyPanel>
      {error && <ErrorBox message={error} />}

      {result && result.weak_concepts.length > 0 && (
        <Card>
          <h2 className="text-lg font-semibold">Concepts to revisit</h2>
          <ul className="mt-3 flex flex-wrap gap-2">
            {result.weak_concepts.map((w) => (
              <li key={w.concept} className="rounded-full bg-bad-soft px-3 py-1.5 text-sm text-bad">
                {w.concept}
                {w.wrong > 1 ? ` ×${w.wrong}` : ""} <span className="font-mono text-xs opacity-75">({w.facts.map((f) => `F${f}`).join(", ")})</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <ol className="space-y-4">
        {quiz.questions.map((q) => {
          const r = byId.get(q.id);
          return (
            <li key={q.id}>
              <Card>
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <p className="text-sm text-muted">Question {q.position}</p>
                  {r && (
                    <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${r.correct ? "bg-ok-soft text-ok" : "bg-bad-soft text-bad"}`}>
                      {r.correct ? "Correct" : r.chosen === null ? "Not answered" : "Incorrect"}
                    </span>
                  )}
                </div>
                <h3 className="mt-1 text-lg font-semibold leading-snug">{q.stem}</h3>
                <ul className="mt-3 space-y-1.5 text-sm">
                  {q.options.map((o, i) => {
                    const isCorrect = r?.correct_index === i;
                    const isChosen = r?.chosen === i;
                    return (
                      <li
                        key={i}
                        className={`rounded-md px-3 py-2 ${isCorrect ? "bg-ok-soft text-ok" : isChosen ? "bg-bad-soft text-bad" : "text-ink/80"}`}
                      >
                        <span className="mr-2 font-semibold">{LETTERS[i]}.</span>
                        {o}
                        {isCorrect && " ✓"}
                        {isChosen && !isCorrect && " (your answer)"}
                      </li>
                    );
                  })}
                </ul>
                <div className="mt-4 space-y-2">
                  {(r?.sources ?? []).map((s) => (
                    <div key={s.idx} className="rounded-lg border-l-4 border-accent bg-paper px-3 py-2 text-sm">
                      <p className="text-xs font-semibold uppercase tracking-wide text-accent-strong">
                        Source · F{s.idx} · p. {s.page} · {s.section}
                      </p>
                      <p className="mt-1">{s.text}</p>
                    </div>
                  ))}
                  {!r && q.fact_idxs && (
                    <p className="text-xs text-muted">Sources: {q.fact_idxs.map((f) => `F${f}`).join(", ")}</p>
                  )}
                </div>
                <div className="mt-3">
                  <Link href={`/verify?question=${q.id}`} className="text-sm font-semibold text-accent-strong underline underline-offset-2">
                    Verify this question
                  </Link>
                </div>
              </Card>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function Quiz() {
  const { id } = useParams<{ id: string }>();
  const { data: loaded, error: loadError, reload: load, setData: setQuiz } = useLoad<QuizOut>(() => getQuiz(id), id);
  const quiz = loaded;
  const [fresh, setResult] = useState<AttemptResult | null>(null);
  const [actionError, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // After a refresh the result is read back from this tab's sessionStorage.
  const result = fresh ?? (quiz?.submitted ? stored<AttemptResult>(`sq_result_${id}`) : null);
  const error = loadError ?? actionError;

  const begin = async () => {
    setBusy(true);
    try {
      setQuiz(await startQuiz(id));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const onSubmitted = useCallback(
    (r: AttemptResult) => {
      setResult(r);
      load(); // reload so fact_idxs appear
      window.scrollTo({ top: 0 });
    },
    [load],
  );

  if (error) return <ErrorBox message={error} onRetry={load} />;
  if (!quiz) return <Loading label="Loading the quiz…" />;
  if (quiz.status === "generating") return <Generating id={id} onDone={load} />;
  if (quiz.status === "failed")
    return (
      <Card className="mx-auto max-w-2xl">
        <h1 className="text-2xl font-semibold">This quiz could not be built</h1>
        <p className="mt-2 text-muted">
          No question passed every check, or the quiz could not be committed on chain. Nothing was counted against you.
        </p>
        <div className="mt-4 flex flex-wrap gap-3">
          <ButtonLink href={`/documents/${quiz.document_id}`} variant="secondary">
            Back to textbook
          </ButtonLink>
          <ButtonLink href={`/documents/${quiz.document_id}/metrics`} variant="ghost">
            See why in Metrics
          </ButtonLink>
        </div>
      </Card>
    );
  if (quiz.submitted || result) return <Results quiz={quiz} result={result} />;
  if (!quiz.started_at) return <StartScreen quiz={quiz} onBegin={begin} busy={busy} />;
  return <Taking quiz={quiz} onSubmitted={onSubmitted} />;
}

export function QuizView() {
  return (
    <AuthedPage>
      <Quiz />
    </AuthedPage>
  );
}
