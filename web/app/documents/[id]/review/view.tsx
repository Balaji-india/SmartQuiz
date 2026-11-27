"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { useLoad } from "@/lib/use-load";
import { AuthedPage } from "@/components/shell";
import { Button, ButtonLink, Card, ErrorBox, Loading, NavyPanel, Stat } from "@/components/ui";
import { ApiError, createQuiz, getReviewSummary } from "@/lib/api";
import type { NothingDueOut, ReviewSummaryOut } from "@/lib/types";

const MAX_REVIEW = 10;

function when(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const mins = Math.round((d.getTime() - Date.now()) / 60000);
  if (mins <= 0) return "now";
  if (mins < 60) return `in ${mins} min`;
  if (mins < 48 * 60) return `in ${Math.round(mins / 60)} h`;
  return d.toLocaleDateString();
}

function Review() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { data: r, error, reload } = useLoad<ReviewSummaryOut>(() => getReviewSummary(id), id);
  const [withShort, setWithShort] = useState(true);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [nothingDue, setNothingDue] = useState<NothingDueOut | null>(null);

  const start = async () => {
    if (!r) return;
    setBusy(true);
    setActionError(null);
    setNothingDue(null);
    try {
      const n = Math.max(1, Math.min(r.due_now, MAX_REVIEW));
      const quiz = await createQuiz(id, n, Math.max(120, n * 60), "review", withShort ? 1 : 0);
      router.push(`/quiz/${quiz.id}`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && (e.body as NothingDueOut | null)?.detail === "Nothing due for review") {
        setNothingDue(e.body as NothingDueOut);
        reload();
      } else setActionError((e as Error).message);
      setBusy(false);
    }
  };

  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!r) return <Loading label="Loading your review queue…" />;

  const n = Math.min(r.due_now, MAX_REVIEW);
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-3xl font-semibold">Review</h1>
          <p className="mt-1 text-muted">Spaced repetition per fact: what you got wrong comes back sooner, what you know comes back later.</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <ButtonLink href={`/documents/${id}/mastery`} variant="secondary">
            Mastery
          </ButtonLink>
          <Link href={`/documents/${id}`} className="text-sm font-semibold text-accent-strong underline underline-offset-2">
            ← Back to textbook
          </Link>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        <Stat label="Due now" value={r.due_now} hint="facts ready to review" />
        <Stat label="Next due" value={when(r.next_due)} hint={r.next_due ? new Date(r.next_due).toLocaleString() : "nothing scheduled"} />
        <Stat label="Cards" value={r.cards} hint="facts you have answered" />
      </div>

      <NavyPanel>
        <p className="text-xs font-semibold uppercase tracking-widest text-accent">Review quiz</p>
        {r.due_now > 0 ? (
          <>
            <h2 className="mt-2 text-2xl font-semibold">
              {n} due fact{n > 1 ? "s" : ""}, most overdue first
            </h2>
            <p className="mt-2 text-white/75">
              Only facts that are due come back, at most two per concept, at the next Bloom level. Every question passes the same gates and its hash is
              committed on chain before you start.
            </p>
            <label className="mt-4 flex items-center gap-2 text-sm text-white/85">
              <input type="checkbox" checked={withShort} onChange={(e) => setWithShort(e.target.checked)} className="h-4 w-4 accent-[var(--color-accent)]" />
              Include one short-answer question (graded from its cited facts)
            </label>
            <Button className="mt-5" onClick={start} disabled={busy}>
              {busy ? "Creating review quiz…" : "Start review quiz"}
            </Button>
          </>
        ) : (
          <>
            <h2 className="mt-2 text-2xl font-semibold">Nothing is due right now</h2>
            <p className="mt-2 text-white/75">
              {r.next_due ? `Your next fact is due ${when(r.next_due)} (${new Date(r.next_due).toLocaleString()}).` : "Answer a quiz first: every graded answer schedules its fact."}
            </p>
            <button
              onClick={reload}
              className="mt-5 inline-flex min-h-11 items-center rounded-lg border border-white/25 px-4 py-2 text-sm font-semibold text-white hover:border-white"
            >
              Check again
            </button>
          </>
        )}
      </NavyPanel>

      {nothingDue && (
        <Card>
          <p className="font-semibold">Nothing due for review</p>
          <p className="mt-1 text-sm text-muted">
            {nothingDue.next_due ? `The next fact is due ${when(nothingDue.next_due)} (${new Date(nothingDue.next_due).toLocaleString()}).` : "No fact is scheduled yet."}
          </p>
        </Card>
      )}
      {actionError && <ErrorBox message={actionError} />}
    </div>
  );
}

export function ReviewView() {
  return (
    <AuthedPage>
      <Review />
    </AuthedPage>
  );
}
