"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { useLoad } from "@/lib/use-load";
import { AuthedPage } from "@/components/shell";
import { Button, ButtonLink, Card, ChainBadge, ErrorBox, Hash, Loading, NavyPanel } from "@/components/ui";
import { createQuiz, getAttempt, getQuiz, getQuizProgress, startQuiz, submitAttempt } from "@/lib/api";
import type { AttemptResult, QuizOut, QuizProgressOut, SourceOut } from "@/lib/types";
import { FactChips } from "@/components/facts";

const POLL_MS = 2000;
const LETTERS = ["A", "B", "C", "D"];
const SHORT_MAX = 500; // SPEC 9.7
const SHORT_IN_PRACTICE = 2;

type Answer = number | string | null;
const isAnswered = (a: Answer) => (typeof a === "string" ? a.trim() !== "" : a !== null);

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
  const [answers, setAnswers] = useState<Answer[]>(() => stored<Answer[]>(key) ?? questions.map(() => null));
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
      // Short answers: trimmed, empty -> null (graded incorrect without an LLM call). MCQ: index or null.
      const payload = answers.map((a, k) =>
        questions[k].qtype === "short" ? (typeof a === "string" && a.trim() ? a.trim().slice(0, SHORT_MAX) : null) : typeof a === "number" ? a : null,
      );
      const result = await submitAttempt(quiz.id, payload, Math.max(0, elapsed));
      store(`sq_result_${quiz.id}`, result);
      onSubmitted(result);
    } catch (e) {
      submitted.current = false;
      setError((e as Error).message);
      setBusy(false);
    }
  }, [answers, onSubmitted, questions, quiz.id, quiz.started_at]);
  const left = useCountdown(quiz.started_at!, quiz.time_limit_sec, submit);

  const choose = (i: Answer) => {
    const next = answers.map((a, k) => (k === current ? i : a));
    setAnswers(next);
    store(key, next);
  };

  const q = questions[current];
  const answered = answers.filter(isAnswered).length;
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
            aria-label={`Question ${k + 1}${isAnswered(answers[k]) ? ", answered" : ""}`}
            className={`h-3 w-7 rounded-full ${k === current ? "bg-accent" : isAnswered(answers[k]) ? "bg-navy" : "bg-line"}`}
          />
        ))}
      </div>
      <Card>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="rounded-full bg-paper px-2.5 py-1 font-semibold capitalize text-muted">{q.bloom_level}</span>
          {q.qtype === "short" && <span className="rounded-full bg-navy px-2.5 py-1 font-semibold text-white">Short answer</span>}
          {q.flagged_general && (
            <span className="rounded-full bg-warn-soft px-2.5 py-1 font-semibold text-warn" title="An independent model could often answer this without your notes">
              General knowledge
            </span>
          )}
        </div>
        <h2 className="mt-3 text-xl font-semibold leading-snug">{q.stem}</h2>
        {q.qtype === "short" ? (
          <div className="mt-5">
            <label htmlFor={`short-${q.id}`} className="text-sm text-muted">
              Answer in a sentence or two, in your own words. It is graded only against the facts this question cites.
            </label>
            <textarea
              id={`short-${q.id}`}
              key={q.id}
              rows={5}
              maxLength={SHORT_MAX}
              value={typeof answers[current] === "string" ? (answers[current] as string) : ""}
              onChange={(e) => choose(e.target.value)}
              className="mt-2 w-full rounded-lg border border-line bg-card px-4 py-3 text-base focus:border-accent"
            />
            <p className="mt-1 text-right text-xs text-muted tabular-nums">
              {typeof answers[current] === "string" ? (answers[current] as string).length : 0} / {SHORT_MAX}
            </p>
          </div>
        ) : (
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
        )}
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

type ResultItem = AttemptResult["results"][number];

function SourceCard({ s, tone = "accent" }: { s: SourceOut; tone?: "accent" | "bad" }) {
  return (
    <div className={`rounded-lg border-l-4 bg-paper px-3 py-2 text-sm ${tone === "bad" ? "border-bad" : "border-accent"}`}>
      <p className="text-xs font-semibold uppercase tracking-wide text-accent-strong">
        Source · F{s.idx} · p. {s.page} · {s.section}
      </p>
      <p className="mt-1">{s.text}</p>
    </div>
  );
}

const VERDICT: Record<"correct" | "partial" | "incorrect", { label: string; chip: string }> = {
  correct: { label: "Correct", chip: "bg-ok-soft text-ok" },
  partial: { label: "Partly correct", chip: "bg-warn-soft text-warn" },
  incorrect: { label: "Incorrect", chip: "bg-bad-soft text-bad" },
};

function statusChip(r: ResultItem): { label: string; chip: string } {
  if (r.qtype === "short") {
    if (!r.grade || r.grade.verdict === null) return { label: "Waiting for educator", chip: "bg-paper text-muted" };
    return VERDICT[r.grade.verdict];
  }
  if (r.correct) return VERDICT.correct;
  return { label: r.chosen === null ? "Not answered" : "Incorrect", chip: "bg-bad-soft text-bad" };
}

function McqResult({ q, r }: { q: QuizOut["questions"][number]; r: ResultItem | undefined }) {
  const byOption = new Map((r?.misconceptions ?? []).map((m) => [m.option, m]));
  const chosenWrong = r && r.chosen !== null && !r.correct ? byOption.get(r.chosen) : undefined;
  const others = (r?.misconceptions ?? []).filter((m) => m !== chosenWrong);
  return (
    <>
      <ul className="mt-3 space-y-1.5 text-sm">
        {q.options.map((o, i) => {
          const isCorrect = r?.correct_index === i;
          const isChosen = r?.chosen === i;
          return (
            <li key={i} className={`rounded-md px-3 py-2 ${isCorrect ? "bg-ok-soft text-ok" : isChosen ? "bg-bad-soft text-bad" : "text-ink/80"}`}>
              <span className="mr-2 font-semibold">{LETTERS[i]}.</span>
              {o}
              {isCorrect && " ✓"}
              {isChosen && !isCorrect && " (your answer)"}
            </li>
          );
        })}
      </ul>
      {chosenWrong && (
        <div className="mt-4 rounded-lg border border-bad/30 bg-bad-soft/50 p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-bad">Why {LETTERS[chosenWrong.option]} is wrong</p>
          <p className="mt-1 text-sm font-semibold">Misconception: {chosenWrong.misconception}</p>
          <div className="mt-2 space-y-2">
            {chosenWrong.sources.map((s) => (
              <SourceCard key={s.idx} s={s} tone="bad" />
            ))}
          </div>
        </div>
      )}
      {others.length > 0 && (
        <details className="mt-3 rounded-lg border border-line px-3 py-2 text-sm">
          <summary className="cursor-pointer font-semibold text-muted">Why the other choices are wrong</summary>
          <ul className="mt-2 space-y-3">
            {others.map((m) => (
              <li key={m.option}>
                <p>
                  <span className="mr-1 font-semibold">{LETTERS[m.option]}.</span>
                  {m.misconception}
                </p>
                <div className="mt-1.5 space-y-2">
                  {m.sources.map((s) => (
                    <SourceCard key={s.idx} s={s} tone="bad" />
                  ))}
                </div>
              </li>
            ))}
          </ul>
        </details>
      )}
    </>
  );
}

function ShortResult({ r }: { r: ResultItem }) {
  const g = r.grade;
  const sources = new Map(r.sources.map((s) => [s.idx, s]));
  const pending = !g || g.verdict === null;
  return (
    <div className="mt-3 space-y-3 text-sm">
      <div className="rounded-lg bg-paper px-3 py-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted">Your answer</p>
        <p className="mt-1 whitespace-pre-wrap">{r.answer_text?.trim() ? r.answer_text : <span className="text-muted">No answer given</span>}</p>
      </div>
      {r.model_answer && (
        <div className="rounded-lg bg-ok-soft/60 px-3 py-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-ok">Model answer</p>
          <p className="mt-1">{r.model_answer}</p>
        </div>
      )}
      {pending ? (
        <div className="rounded-lg border border-warn/40 bg-warn-soft p-3 text-warn" role="status">
          <p className="font-semibold">Waiting for educator</p>
          <p className="mt-1">
            The checker was not sure enough{g?.confidence != null ? ` (confidence ${g.confidence} < 70)` : ""}, so an educator will grade this answer. It
            does not count in your score until then.
          </p>
        </div>
      ) : (
        <div className="rounded-lg border border-line p-3">
          <p className="flex flex-wrap items-center gap-2">
            <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${VERDICT[g.verdict!].chip}`}>{VERDICT[g.verdict!].label}</span>
            <span className="text-xs text-muted">
              graded by {g.by === "educator" ? "an educator" : "the checker model"}
              {g.confidence != null && ` · confidence ${g.confidence}`}
              {g.deferred && g.by === "educator" && " · after deferral"}
            </span>
          </p>
          {g.reason && <p className="mt-2">{g.reason}</p>}
          <div className="mt-2">
            <FactChips idxs={g.fact_idxs} facts={sources} label="Graded against" />
          </div>
        </div>
      )}
    </div>
  );
}

function Results({ quiz, result, onRefresh }: { quiz: QuizOut; result: AttemptResult | null; onRefresh: () => Promise<void> }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const byId = new Map(result?.results.map((r) => [r.question_id, r]));

  const newQuiz = async () => {
    setBusy(true);
    setError(null);
    try {
      const next = await createQuiz(quiz.document_id, 10, 600, "practice", SHORT_IN_PRACTICE);
      router.push(`/quiz/${next.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  const refresh = async () => {
    setRefreshing(true);
    setError(null);
    try {
      await onRefresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <div className="space-y-6">
      <NavyPanel>
        <p className="text-xs font-semibold uppercase tracking-widest text-accent">{quiz.mode === "review" ? "Review results" : "Results"}</p>
        {result ? (
          <>
            <h1 className="mt-2 text-4xl font-semibold">
              {result.score} <span className="text-white/50">/ {result.total}</span>
            </h1>
            {result.pending_review > 0 && (
              <p className="mt-2 text-sm text-white/75">
                + {result.pending_review} short answer{result.pending_review > 1 ? "s" : ""} waiting for an educator; the score updates once graded.
              </p>
            )}
          </>
        ) : (
          <h1 className="mt-2 text-2xl font-semibold">This quiz has been submitted.</h1>
        )}
        <div className="mt-5 flex flex-wrap gap-3">
          <Button onClick={newQuiz} disabled={busy}>
            {busy ? "Creating…" : "New quiz (no repeats)"}
          </Button>
          {result && result.pending_review > 0 && (
            <button
              onClick={refresh}
              disabled={refreshing}
              className="inline-flex min-h-11 items-center rounded-lg border border-white/25 px-4 py-2 text-sm font-semibold text-white hover:border-white disabled:opacity-50"
            >
              {refreshing ? "Checking…" : "Check grading again"}
            </button>
          )}
          <Link href={`/documents/${quiz.document_id}/mastery`} className="inline-flex min-h-11 items-center rounded-lg border border-white/25 px-4 py-2 text-sm font-semibold text-white hover:border-white">
            Mastery
          </Link>
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
          const chip = r ? statusChip(r) : null;
          return (
            <li key={q.id}>
              <Card>
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <p className="text-sm text-muted">
                    Question {q.position}
                    {q.qtype === "short" && " · short answer"} · <span className="capitalize">{q.bloom_level}</span>
                  </p>
                  {chip && <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${chip.chip}`}>{chip.label}</span>}
                </div>
                <h3 className="mt-1 text-lg font-semibold leading-snug">{q.stem}</h3>
                {q.qtype === "short" ? r && <ShortResult r={r} /> : <McqResult q={q} r={r} />}
                <div className="mt-4 space-y-2">
                  {(r?.sources ?? []).map((s) => (
                    <SourceCard key={s.idx} s={s} />
                  ))}
                  {!r && q.fact_idxs && <p className="text-xs text-muted">Sources: {q.fact_idxs.map((f) => `F${f}`).join(", ")}</p>}
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
  // After a refresh the result is reloaded from the API; this tab's sessionStorage is only a fallback.
  // Not needed right after submit: the submit response is the result.
  const attemptId = fresh ? null : (quiz?.attempt_id ?? null);
  const {
    data: loadedResult,
    error: resultError,
    reload: reloadResult,
  } = useLoad<AttemptResult | null>(() => (attemptId ? getAttempt(attemptId) : Promise.resolve(null)), attemptId);
  const fallback = quiz?.submitted ? stored<AttemptResult>(`sq_result_${id}`) : null;
  const result = fresh ?? loadedResult ?? fallback;
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

  // "Check grading again": reload through GET /attempts/{id} (an educator may have graded a deferred answer).
  const refreshResult = async () => {
    const attempt = result?.attempt_id ?? quiz?.attempt_id;
    if (!attempt) return;
    const next = await getAttempt(attempt);
    store(`sq_result_${id}`, next);
    setResult(next);
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
  if (quiz.submitted && !result) {
    if (resultError) return <ErrorBox message={resultError} onRetry={reloadResult} />;
    return <Loading label="Loading your result…" />;
  }
  if (quiz.submitted || result) return <Results quiz={quiz} result={result} onRefresh={refreshResult} />;
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
