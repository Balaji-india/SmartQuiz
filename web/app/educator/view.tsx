"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { useLoad, useMe } from "@/lib/use-load";
import { AuthedPage } from "@/components/shell";
import { Button, Card, ChainBadge, ErrorBox, ExplorerLink, Hash, Loading, NavyPanel, Stat } from "@/components/ui";
import { BadgeCard, RevokeForm } from "@/components/badges";
import {
  anchorResults,
  cosignDocument,
  getEducatorResults,
  getGradingQueue,
  gradeAnswer,
  listAllBadges,
  listEducatorDocuments,
  revokeBadge,
  revokeDocument,
} from "@/lib/api";
import type {
  AnchorOut,
  CoSignResultOut,
  EducatorBadgeOut,
  EducatorDocumentOut,
  EducatorResultsOut,
  GradeDoneOut,
  GradingItemOut,
  Verdict,
} from "@/lib/types";

const TABS = [
  { id: "documents", label: "Documents" },
  { id: "grading", label: "Grading queue" },
  { id: "results", label: "Results" },
  { id: "badges", label: "Badges" },
] as const;
type Tab = (typeof TABS)[number]["id"];

/** The explorer link of another tx, from a known explorer URL of the same network (…/tx/0x…). */
function txUrl(knownExplorerUrl: string | null, tx: string | null): string | null {
  if (!knownExplorerUrl || !tx) return null;
  return /\/tx\/0x[0-9a-fA-F]+$/.test(knownExplorerUrl) ? knownExplorerUrl.replace(/0x[0-9a-fA-F]+$/, tx) : null;
}

// ---- Documents: co-sign, revoke ----
function DocumentRow({ doc, onChange }: { doc: EducatorDocumentOut; onChange: (d: EducatorDocumentOut) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [signed, setSigned] = useState<CoSignResultOut | null>(null);
  const registered = doc.register_tx !== null && doc.fact_root !== null;

  const cosign = async () => {
    setBusy(true);
    setError(null);
    try {
      const out = await cosignDocument(doc.id);
      setSigned(out);
      onChange({ ...doc, cosign: { educator_address: out.educator_address, at: new Date().toISOString(), cosign_tx: out.cosign_tx } });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <li className={`rounded-xl border p-5 ${doc.revoked ? "border-bad/40 bg-bad-soft/40" : "border-line bg-card"}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-lg font-semibold">{doc.filename}</h3>
          <p className="text-sm text-muted">
            {doc.fact_count} facts · {doc.sections_count} sections · uploaded {new Date(doc.created_at).toLocaleDateString()}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {doc.revoked && <span className="rounded-full bg-bad px-3 py-1 text-xs font-semibold text-white">Revoked</span>}
          {doc.cosign && !doc.revoked && <span className="rounded-full bg-ok-soft px-3 py-1 text-xs font-semibold text-ok">✓ Co-signed</span>}
          <ChainBadge status={doc.chain_status} />
        </div>
      </div>
      <div className="mt-3 space-y-1.5 text-sm">
        {doc.fact_root ? <Hash value={doc.fact_root} label="Fact root" /> : <p className="text-muted">Not registered on chain yet, so it cannot be co-signed.</p>}
        {doc.cosign && (
          <p className="flex flex-wrap items-center gap-2">
            <Hash value={doc.cosign.educator_address} label="Co-signed by" />
            <span className="text-xs text-muted">{new Date(doc.cosign.at).toLocaleString()}</span>
            <ExplorerLink url={signed?.explorer_url ?? txUrl(doc.explorer_url, doc.cosign.cosign_tx)}>Co-sign tx ↗</ExplorerLink>
          </p>
        )}
        {signed && <Hash value={signed.signature} label="EIP-712 signature" />}
      </div>
      {!doc.revoked && (
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button onClick={cosign} disabled={busy || !registered} className="min-h-9 px-3 py-1 text-xs">
            {busy ? "Signing and sending…" : doc.cosign ? "Co-sign again" : "Co-sign fact root"}
          </Button>
          <RevokeForm what="document" onRevoke={async (reason) => onChange(await revokeDocument(doc.id, reason))} />
        </div>
      )}
      {error && (
        <div className="mt-3">
          <ErrorBox message={error} />
        </div>
      )}
    </li>
  );
}

function DocumentsTab() {
  const { data, error, reload, setData } = useLoad<EducatorDocumentOut[]>(listEducatorDocuments, "docs");
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!data) return <Loading label="Loading documents…" />;
  if (data.length === 0) return <Card><p className="text-sm text-muted">No ready documents yet.</p></Card>;
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted">
        Co-signing puts your EIP-712 signature over the document&apos;s fact root on chain: you vouch that these facts are the course material. Revoking marks
        the document on chain; its questions then show as revoked on Verify and no new badges are minted for it.
      </p>
      <ul className="space-y-3">
        {data.map((d) => (
          <DocumentRow key={d.id} doc={d} onChange={(next) => setData(data.map((x) => (x.id === next.id ? next : x)))} />
        ))}
      </ul>
    </div>
  );
}

// ---- Grading queue ----
const VERDICTS: { v: Verdict; label: string; cls: string }[] = [
  { v: "correct", label: "Correct", cls: "bg-ok text-white hover:opacity-90" },
  { v: "partial", label: "Partial", cls: "bg-warn text-white hover:opacity-90" },
  { v: "incorrect", label: "Incorrect", cls: "bg-bad text-white hover:opacity-90" },
];

function GradingItem({ item, onDone }: { item: GradingItemOut; onDone: (out: GradeDoneOut, verdict: Verdict) => void }) {
  const [busy, setBusy] = useState<Verdict | null>(null);
  const [error, setError] = useState<string | null>(null);
  const grade = async (v: Verdict) => {
    setBusy(v);
    setError(null);
    try {
      onDone(await gradeAnswer(item.grade_id, v), v);
    } catch (e) {
      setError((e as Error).message);
      setBusy(null);
    }
  };
  return (
    <li className="rounded-xl border border-line bg-card p-5">
      <p className="text-xs font-semibold uppercase tracking-widest text-accent-strong">Short answer · deferred by the checker</p>
      <h3 className="mt-1 text-lg font-semibold">{item.stem}</h3>
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <div className="rounded-lg bg-paper p-3 text-sm">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">Learner&apos;s answer</p>
          <p className="mt-1 whitespace-pre-wrap">{item.answer_text || <span className="text-muted">(blank)</span>}</p>
        </div>
        <div className="rounded-lg bg-ok-soft/60 p-3 text-sm">
          <p className="text-xs font-semibold uppercase tracking-wide text-ok">Model answer</p>
          <p className="mt-1">{item.model_answer ?? "—"}</p>
        </div>
      </div>
      <div className="mt-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted">Grade only against these facts</p>
        <ul className="mt-2 space-y-2">
          {item.facts.map((f) => (
            <li key={f.idx} className="rounded-lg border-l-4 border-accent bg-paper px-3 py-2 text-sm">
              <span className="font-mono text-xs font-semibold text-accent-strong">
                F{f.idx} · p. {f.page}
              </span>
              <p className="mt-0.5">{f.text}</p>
            </li>
          ))}
        </ul>
      </div>
      <div className="mt-4 rounded-lg border border-line p-3 text-sm">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted">Checker model</p>
        <p className="mt-1">
          <span className="font-semibold capitalize">{item.checker.verdict ?? "no verdict"}</span>
          {item.checker.confidence !== null && <span className="text-muted"> · confidence {item.checker.confidence} (below 70, so it came to you)</span>}
        </p>
        {item.checker.reason && <p className="mt-1 text-muted">{item.checker.reason}</p>}
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold">Your grade:</span>
        {VERDICTS.map(({ v, label, cls }) => (
          <button
            key={v}
            onClick={() => grade(v)}
            disabled={busy !== null}
            className={`inline-flex min-h-10 items-center rounded-lg px-4 py-2 text-sm font-semibold disabled:opacity-50 ${cls}`}
          >
            {busy === v ? "Saving…" : label}
          </button>
        ))}
      </div>
      {error && (
        <div className="mt-3">
          <ErrorBox message={error} />
        </div>
      )}
    </li>
  );
}

function GradingTab() {
  const { data, error, reload, setData } = useLoad<GradingItemOut[]>(getGradingQueue, "grading");
  const [done, setDone] = useState<(GradeDoneOut & { verdict: Verdict })[]>([]);
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!data) return <Loading label="Loading the grading queue…" />;
  return (
    <div className="space-y-4">
      {done.length > 0 && (
        <Card>
          <h3 className="font-semibold">Graded just now</h3>
          <ul className="mt-2 space-y-1 text-sm">
            {done.map((d) => (
              <li key={d.grade_id} className="flex flex-wrap items-center gap-2">
                <span className="capitalize">{d.verdict}</span>
                <span className="text-muted">
                  · attempt {d.attempt_id.slice(0, 8)}… {d.grading_status === "final" ? "is final and ready to anchor (Results tab)" : "still has answers waiting"}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}
      {data.length === 0 ? (
        <Card>
          <p className="text-sm text-muted">Nothing to grade. The checker defers a short answer here when its confidence is below 70.</p>
          <button onClick={reload} className="mt-2 text-sm font-semibold text-accent-strong underline underline-offset-2">
            Check again
          </button>
        </Card>
      ) : (
        <ul className="space-y-4">
          {data.map((item) => (
            <GradingItem
              key={item.grade_id}
              item={item}
              onDone={(out, verdict) => {
                setData(data.filter((x) => x.grade_id !== item.grade_id));
                setDone((prev) => [{ ...out, verdict }, ...prev]);
              }}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

// ---- Results: anchor ----
function ResultsTab() {
  const { data, error, reload } = useLoad<EducatorResultsOut>(getEducatorResults, "results");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [anchored, setAnchored] = useState<AnchorOut | null>(null);

  const anchor = async () => {
    setBusy(true);
    setActionError(null);
    try {
      setAnchored(await anchorResults());
      reload();
    } catch (e) {
      setActionError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!data) return <Loading label="Loading results…" />;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        <Stat label="Waiting to anchor" value={data.unanchored} hint="final attempts, all learners" />
        <Stat label="Waiting for grading" value={data.pending_grading} hint="anchored once graded" />
        <Stat label="Batches on chain" value={data.batches.length} />
      </div>
      <NavyPanel>
        <p className="text-xs font-semibold uppercase tracking-widest text-accent">Anchor results</p>
        <h2 className="mt-2 text-2xl font-semibold">
          {data.unanchored > 0 ? `${data.unanchored} result${data.unanchored > 1 ? "s" : ""} ready` : "Everything final is anchored"}
        </h2>
        <p className="mt-2 text-white/75">
          Each attempt hash (quiz, answers, score, grades, salt) becomes a Merkle leaf; one transaction puts the batch root on chain. Only hashes go on chain.
        </p>
        <Button className="mt-5" onClick={anchor} disabled={busy || data.unanchored === 0}>
          {busy ? "Anchoring on Polygon Amoy…" : "Anchor now"}
        </Button>
        {anchored && (
          <div className="mt-5 space-y-1.5 rounded-lg bg-white/10 p-4 text-sm">
            <p className="font-semibold">
              ✓ Anchored {anchored.count} result{anchored.count > 1 ? "s" : ""}
            </p>
            <div>
              <Hash value={anchored.root} label="Root" dark />
            </div>
            <div>
              <Hash value={anchored.batch_id} label="Batch id" dark />
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <ChainBadge status={anchored.chain_status} />
              {anchored.explorer_url && (
                <a href={anchored.explorer_url} target="_blank" rel="noreferrer" className="font-semibold text-accent underline underline-offset-2">
                  Anchor transaction ↗
                </a>
              )}
            </div>
          </div>
        )}
      </NavyPanel>
      {actionError && <ErrorBox message={actionError} />}
      {data.batches.length > 0 && (
        <Card>
          <h3 className="font-semibold">Anchored batches</h3>
          <ul className="mt-3 divide-y divide-line">
            {data.batches.map((b) => (
              <li key={b.batch_id} className="flex flex-wrap items-center justify-between gap-3 py-3 text-sm">
                <div className="space-y-1">
                  <Hash value={b.root} label="Root" />
                  <p className="text-xs text-muted">
                    {b.count} result{b.count > 1 ? "s" : ""} · {new Date(b.created_at).toLocaleString()}
                  </p>
                </div>
                <ExplorerLink url={b.explorer_url}>Tx ↗</ExplorerLink>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-muted">A learner checks one result on Verify → Result with the attempt ID (the “Verify my result” button on their results).</p>
        </Card>
      )}
    </div>
  );
}

// ---- Badges: revoke ----
function BadgesTab() {
  const { data, error, reload, setData } = useLoad<EducatorBadgeOut[]>(listAllBadges, "badges");
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!data) return <Loading label="Loading badges…" />;
  if (data.length === 0) return <Card><p className="text-sm text-muted">No badges minted yet.</p></Card>;
  return (
    <ul className="grid gap-4 md:grid-cols-2">
      {data.map((b) => (
        <BadgeCard key={b.id} badge={b} subtitle={`Learner: ${b.learner_name}`}>
          {!b.revoked && (
            <div className="mt-4">
              <RevokeForm
                what="badge"
                onRevoke={async (reason) => {
                  const out = await revokeBadge(b.id, reason);
                  setData(data.map((x) => (x.id === b.id ? { ...x, ...out } : x)));
                }}
              />
            </div>
          )}
        </BadgeCard>
      ))}
    </ul>
  );
}

function Educator() {
  const params = useSearchParams();
  const router = useRouter();
  const { data: me, error } = useMe();
  const raw = params.get("tab");
  const tab: Tab = TABS.some((t) => t.id === raw) ? (raw as Tab) : "documents";

  if (error) return <ErrorBox message={error} />;
  if (!me) return <Loading />;
  if (me.role !== "educator")
    return (
      <Card className="mx-auto max-w-xl">
        <h1 className="text-2xl font-semibold">Educators only</h1>
        <p className="mt-2 text-sm text-muted">
          This page is for the course educators (co-signing, grading, anchoring, revocation). An educator account is set with{" "}
          <code className="rounded bg-paper px-1 font-mono text-xs">api/scripts/make_educator.py &lt;email&gt;</code>.
        </p>
        <Link href="/" className="mt-4 inline-block text-sm font-semibold text-accent-strong underline underline-offset-2">
          ← Back to my documents
        </Link>
      </Card>
    );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold">Educator</h1>
        <p className="mt-1 text-muted">Every action here is signed by the educator wallet (EIP-712); the issuer sends the transaction and pays the gas.</p>
      </div>
      <div className="inline-flex flex-wrap rounded-lg border border-line bg-card p-1" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => router.replace(`/educator?tab=${t.id}`)}
            className={`rounded-md px-4 py-2 text-sm font-semibold ${tab === t.id ? "bg-navy text-white" : "text-muted hover:text-ink"}`}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === "documents" && <DocumentsTab />}
      {tab === "grading" && <GradingTab />}
      {tab === "results" && <ResultsTab />}
      {tab === "badges" && <BadgesTab />}
    </div>
  );
}

export function EducatorView() {
  return (
    <AuthedPage>
      <Educator />
    </AuthedPage>
  );
}
