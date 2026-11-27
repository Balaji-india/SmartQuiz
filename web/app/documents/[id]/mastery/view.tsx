"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { useLoad } from "@/lib/use-load";
import { AuthedPage } from "@/components/shell";
import { Button, ButtonLink, Card, ErrorBox, Loading, Stat } from "@/components/ui";
import { FactChips, factIndex, type FactRef } from "@/components/facts";
import { claimBadge, createRevision, getMastery, getRevision, getTextbook, listBadges } from "@/lib/api";
import type { BadgeOut, ConceptMastery, MasteryOut, MasteryStatus, RevisionNote, RevisionOut, TextbookOut } from "@/lib/types";

const STATUS: Record<MasteryStatus, { label: string; hint: string; chip: string; bar: string }> = {
  weak: { label: "Weak", hint: "below 40%", chip: "bg-bad-soft text-bad", bar: "bg-bad" },
  learning: { label: "Learning", hint: "40–95%", chip: "bg-warn-soft text-warn", bar: "bg-accent" },
  untested: { label: "Untested", hint: "not answered yet", chip: "bg-paper text-muted", bar: "bg-line" },
  mastered: { label: "Mastered", hint: "95% or more", chip: "bg-ok-soft text-ok", bar: "bg-ok" },
};
const ORDER: MasteryStatus[] = ["weak", "learning", "untested", "mastered"];

function ConceptRow({
  c,
  facts,
  onRevise,
  busy,
  badge,
  onClaim,
  claiming,
}: {
  c: ConceptMastery;
  facts: Map<number, FactRef> | null;
  onRevise: (concept: string) => void;
  busy: boolean;
  badge: BadgeOut | null;
  onClaim: (concept: string) => void;
  claiming: string | null;
}) {
  const s = STATUS[c.status];
  const pct = Math.round(c.p_mastery * 100);
  return (
    <li className="rounded-lg border border-line p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-semibold">{c.concept}</p>
          <p className="text-xs text-muted">
            {c.section} · answered {c.answered}×
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {(c.status === "weak" || c.status === "learning") && (
            <Button variant="ghost" className="min-h-9 px-3 py-1 text-xs" onClick={() => onRevise(c.concept)} disabled={busy}>
              Revise
            </Button>
          )}
          {c.status === "mastered" &&
            (c.badge_id ? (
              <Link
                href={badge?.token_id != null ? `/verify?badge=${badge.token_id}` : "/profile"}
                className="rounded-full bg-ok-soft px-3 py-1 text-xs font-semibold text-ok hover:underline"
              >
                ✓ Badge{badge?.token_id != null ? ` #${badge.token_id}` : " minted"} · Verify
              </Link>
            ) : (
              <Button
                className="min-h-9 px-3 py-1 text-xs"
                onClick={() => onClaim(c.concept)}
                disabled={claiming !== null}
                title="Mint a soulbound badge for this concept on Polygon Amoy"
              >
                {claiming === c.concept ? "Minting on Polygon Amoy…" : "Claim badge"}
              </Button>
            ))}
        </div>
      </div>
      <div className="mt-3 flex items-center gap-3">
        <div className="h-2 flex-1 rounded-full bg-paper" role="meter" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label={`${c.concept} mastery`}>
          <div className={`h-full rounded-full ${s.bar}`} style={{ width: `${Math.max(2, pct)}%` }} />
        </div>
        <span className="w-10 text-right text-sm font-semibold tabular-nums">{pct}%</span>
      </div>
      <div className="mt-3">
        <FactChips idxs={c.fact_idxs} facts={facts} />
      </div>
    </li>
  );
}

function Note({ note, facts }: { note: RevisionNote; facts: Map<number, FactRef> | null }) {
  return (
    <li className="rounded-lg border border-line p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-semibold">{note.concept}</h3>
        <p className="text-xs text-muted">
          {new Date(note.created_at).toLocaleString()}
          {note.dropped > 0 && ` · ${note.dropped} sentence${note.dropped > 1 ? "s" : ""} dropped by Gate 1`}
        </p>
      </div>
      {note.sentences.length === 0 ? (
        <p className="mt-2 text-sm text-muted">Every sentence failed the grounding check, so nothing is shown. Try again later.</p>
      ) : (
        <ol className="mt-3 space-y-3">
          {note.sentences.map((s, i) => (
            <li key={i} className="text-sm">
              <p>{s.text}</p>
              <div className="mt-1">
                <FactChips idxs={s.fact_idxs} facts={facts} label="Cited" />
              </div>
            </li>
          ))}
        </ol>
      )}
    </li>
  );
}

function Mastery() {
  const { id } = useParams<{ id: string }>();
  const { data: m, error, reload } = useLoad<MasteryOut>(() => getMastery(id), id);
  const { data: book } = useLoad<TextbookOut>(() => getTextbook(id), id);
  const { data: loadedNotes, error: notesError, reload: reloadNotes } = useLoad<RevisionOut>(() => getRevision(id), id);
  const [generated, setGenerated] = useState<RevisionOut | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const { data: badges, reload: reloadBadges } = useLoad<BadgeOut[]>(listBadges, id);
  const [claiming, setClaiming] = useState<string | null>(null);
  const [claimError, setClaimError] = useState<string | null>(null);
  const [claimed, setClaimed] = useState<BadgeOut | null>(null);
  const facts = book ? factIndex(book.sections) : null;

  const claim = async (concept: string) => {
    setClaiming(concept);
    setClaimError(null);
    setClaimed(null);
    try {
      // Anchors this learner's unanchored results first, then mints (SPEC 9.9); takes a few block times.
      setClaimed(await claimBadge(id, concept));
      reload();
      reloadBadges();
    } catch (e) {
      setClaimError(`${concept}: ${(e as Error).message}`);
    } finally {
      setClaiming(null);
    }
  };

  const revise = async (concept: string | null) => {
    setBusy(concept ?? "weakest");
    setActionError(null);
    try {
      setGenerated(await createRevision(id, concept ? [concept] : null));
      reloadNotes();
    } catch (e) {
      setActionError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!m) return <Loading label="Loading your mastery…" />;

  const notes = loadedNotes ?? generated;
  const revisable = m.summary.weak + m.summary.learning > 0;
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-3xl font-semibold">Mastery</h1>
          <p className="mt-1 text-muted">Your gap report: how sure we are that you know each concept, from every graded answer.</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <ButtonLink href={`/documents/${id}/review`} variant="secondary">
            Review queue
          </ButtonLink>
          <Link href={`/documents/${id}`} className="text-sm font-semibold text-accent-strong underline underline-offset-2">
            ← Back to textbook
          </Link>
        </div>
      </div>

      {claimed && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-ok-soft px-5 py-4 text-ok" role="status">
          <p className="font-semibold">
            ✓ Badge #{claimed.token_id} minted for “{claimed.concept}” to {claimed.custodial ? "your custodial address" : "your wallet"}.
          </p>
          <div className="flex flex-wrap items-center gap-4 text-sm font-semibold">
            <Link href={`/verify?badge=${claimed.token_id}`} className="underline underline-offset-2">
              Verify it
            </Link>
            <Link href="/profile" className="underline underline-offset-2">
              My badges
            </Link>
          </div>
        </div>
      )}
      {claimError && <ErrorBox message={claimError} />}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {ORDER.map((s) => (
          <Stat key={s} label={STATUS[s].label} value={m.summary[s]} hint={STATUS[s].hint} />
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_minmax(0,420px)]">
        <div className="space-y-6">
          {ORDER.map((status) => {
            const list = m.concepts.filter((c) => c.status === status);
            if (list.length === 0) return null;
            return (
              <Card key={status}>
                <h2 className="flex items-center gap-2 text-lg font-semibold">
                  <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${STATUS[status].chip}`}>{STATUS[status].label}</span>
                  {list.length} concept{list.length > 1 ? "s" : ""}
                </h2>
                <ul className="mt-4 space-y-3">
                  {list.map((c) => (
                    <ConceptRow
                      key={c.concept}
                      c={c}
                      facts={facts}
                      onRevise={revise}
                      busy={busy !== null}
                      badge={badges?.find((b) => b.id === c.badge_id) ?? null}
                      onClaim={claim}
                      claiming={claiming}
                    />
                  ))}
                </ul>
              </Card>
            );
          })}
        </div>

        <Card className="h-fit lg:sticky lg:top-20">
          <h2 className="text-lg font-semibold">Revision notes</h2>
          <p className="mt-1 text-sm text-muted">
            Written only from your notes. Every sentence cites its facts and passed the grounding check; unsupported sentences are dropped.
          </p>
          <Button className="mt-4 w-full" onClick={() => revise(null)} disabled={busy !== null || !revisable}>
            {busy === "weakest" ? "Writing notes…" : busy ? `Writing notes for ${busy}…` : "Generate notes for my 3 weakest concepts"}
          </Button>
          {!revisable && <p className="mt-2 text-xs text-muted">Notes are for weak or learning concepts. Take a quiz first.</p>}
          {actionError && (
            <div className="mt-3">
              <ErrorBox message={actionError} />
            </div>
          )}
          {notesError && (
            <div className="mt-3">
              <ErrorBox message={notesError} onRetry={reloadNotes} />
            </div>
          )}
          {notes && notes.notes.length > 0 ? (
            <ul className="mt-4 space-y-3">
              {notes.notes.map((n) => (
                <Note key={n.concept} note={n} facts={facts} />
              ))}
            </ul>
          ) : (
            notes && <p className="mt-4 text-sm text-muted">No revision notes yet.</p>
          )}
        </Card>
      </div>
    </div>
  );
}

export function MasteryView() {
  return (
    <AuthedPage>
      <Mastery />
    </AuthedPage>
  );
}
