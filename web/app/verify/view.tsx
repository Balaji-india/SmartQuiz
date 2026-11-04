"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";
import { useLoad, useToken } from "@/lib/use-load";
import { Page } from "@/components/shell";
import { Button, Card, ChainBadge, ErrorBox, ExplorerLink, Hash, Loading } from "@/components/ui";
import { verifyFact, verifyQuestion, verifyQuiz } from "@/lib/api";
import type { ChainStatus, VerifiedFact, VerifyQuestionOut, VerifyQuizOut } from "@/lib/types";

type Tab = "question" | "quiz";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** true → green, false → red, null → the offline badge (never red). */
function Verdict({ value, status, yes, no }: { value: boolean | null; status: ChainStatus; yes: string; no: string }) {
  if (value === null)
    return (
      <div className="flex flex-wrap items-center gap-3 rounded-xl bg-warn-soft px-5 py-4 text-warn">
        <ChainBadge status={status === "confirmed" ? "offline" : status} />
        <span className="text-sm">The chain could not be read, so this was not checked. It is not a failure.</span>
      </div>
    );
  return value ? (
    <div className="rounded-xl bg-ok px-5 py-4 font-display text-xl font-semibold text-white">✓ {yes}</div>
  ) : (
    <div className="rounded-xl bg-bad px-5 py-4 font-display text-xl font-semibold text-white">✗ {no}</div>
  );
}

function FactCard({ fact, documentId, chainStatus }: { fact: VerifiedFact; documentId: string; chainStatus: ChainStatus }) {
  const [text, setText] = useState(fact.text);
  const [leaf, setLeaf] = useState(fact.leaf);
  const [verified, setVerified] = useState<boolean | null>(fact.verified_on_chain);
  const [status, setStatus] = useState<ChainStatus>(chainStatus);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showProof, setShowProof] = useState(false);
  const edited = text !== fact.text;

  const recheck = async () => {
    setBusy(true);
    setError(null);
    try {
      const out = await verifyFact(documentId, fact.idx, text);
      setLeaf(out.leaf);
      setVerified(out.verified_on_chain);
      setStatus(out.chain_status);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-mono text-sm font-semibold text-accent-strong">
          Fact F{fact.idx} · page {fact.page}
        </p>
        {edited && <span className="rounded-full bg-warn-soft px-2.5 py-1 text-xs font-semibold text-warn">Edited — press Re-check</span>}
      </div>
      <label className="block text-sm font-medium">
        Fact text (edit one word to test tampering)
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={3}
          className="mt-1 w-full rounded-lg border border-line bg-white px-3 py-2 text-base leading-relaxed outline-none focus:border-accent"
        />
      </label>
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={recheck} disabled={busy} variant="secondary">
          {busy ? "Checking on chain…" : "Re-check"}
        </Button>
        {edited && (
          <button onClick={() => setText(fact.text)} className="text-sm font-semibold text-accent-strong underline underline-offset-2">
            Restore original
          </button>
        )}
      </div>
      {error && <ErrorBox message={error} />}
      <Verdict value={verified} status={status} yes="Verified on Polygon Amoy" no="Not verified — this text is not in the registered document" />
      <div className="space-y-2 text-sm">
        <Hash value={leaf} label="Leaf" />
        <div>
          <button onClick={() => setShowProof((s) => !s)} className="font-semibold text-accent-strong" aria-expanded={showProof}>
            {showProof ? "Hide" : "Show"} Merkle proof ({fact.proof.length} hashes)
          </button>
          {showProof && (
            <ol className="mt-2 space-y-1">
              {fact.proof.map((p, i) => (
                <li key={i} className="flex items-center gap-2">
                  <span className="w-5 text-right text-xs text-muted">{i + 1}</span>
                  <Hash value={p} />
                </li>
              ))}
            </ol>
          )}
        </div>
      </div>
    </Card>
  );
}

function QuestionResult({ id }: { id: string }) {
  const { data, error, status } = useLoad<VerifyQuestionOut>(() => verifyQuestion(id), id);

  if (error)
    return <ErrorBox message={status === 409 ? "Available after the quiz is submitted." : status === 404 ? "No question with that ID." : error} />;
  if (!data) return <Loading label="Reading the proof from the chain…" />;
  const rootsMatch = data.onchain_root === null ? null : data.onchain_root === data.db_root;
  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <p className="text-xs font-semibold uppercase tracking-widest text-muted">Question</p>
          <ChainBadge status={data.chain_status} />
        </div>
        <h2 className="mt-2 text-xl font-semibold leading-snug">{data.stem}</h2>
        <dl className="mt-4 space-y-2 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <dt className="w-28 text-muted">Root in DB</dt>
            <dd>
              <Hash value={data.db_root} />
            </dd>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <dt className="w-28 text-muted">Root on chain</dt>
            <dd>{data.onchain_root ? <Hash value={data.onchain_root} /> : <span className="text-muted">not read</span>}</dd>
            {rootsMatch !== null && (
              <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${rootsMatch ? "bg-ok-soft text-ok" : "bg-bad-soft text-bad"}`}>
                {rootsMatch ? "match" : "mismatch"}
              </span>
            )}
          </div>
          {data.registry_address && (
            <div className="flex flex-wrap items-center gap-2">
              <dt className="w-28 text-muted">Registry</dt>
              <dd>
                <Hash value={data.registry_address} />
              </dd>
            </div>
          )}
        </dl>
        <div className="mt-3">
          <ExplorerLink url={data.explorer_url}>Document registration on Polygon Amoy ↗</ExplorerLink>
        </div>
      </Card>
      {data.facts.map((f) => (
        <FactCard key={f.idx} fact={f} documentId={data.document_id} chainStatus={data.chain_status} />
      ))}
    </div>
  );
}

function QuizResult({ id }: { id: string }) {
  const { data, error, status } = useLoad<VerifyQuizOut>(() => verifyQuiz(id), id);

  if (error) return <ErrorBox message={status === 404 ? "No quiz with that ID." : status === 409 ? "This quiz is not ready yet." : error} />;
  if (!data) return <Loading label="Recomputing the quiz hash…" />;
  return (
    <Card className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <p className="text-xs font-semibold uppercase tracking-widest text-muted">Quiz integrity</p>
        <ChainBadge status={data.chain_status} />
      </div>
      <dl className="space-y-2 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <dt className="w-36 text-muted">Recomputed now</dt>
          <dd>
            <Hash value={data.recomputed_hash} />
          </dd>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <dt className="w-36 text-muted">Committed on chain</dt>
          <dd>{data.onchain_hash ? <Hash value={data.onchain_hash} /> : <span className="text-muted">not read</span>}</dd>
        </div>
      </dl>
      <Verdict
        value={data.match}
        status={data.chain_status}
        yes="Match — the quiz is exactly what was committed before the attempt"
        no="Mismatch — the stored quiz differs from what was committed"
      />
      <ExplorerLink url={data.explorer_url}>Commit transaction on Polygon Amoy ↗</ExplorerLink>
    </Card>
  );
}

function Verify() {
  const params = useSearchParams();
  const initialTab: Tab = params.get("quiz") ? "quiz" : "question";
  const current = params.get(initialTab) ?? "";
  // Re-keyed on the URL, so the form starts from ?question= / ?quiz= without syncing state in an effect.
  return <VerifyForm key={`${initialTab}:${current}`} initialTab={initialTab} current={current} />;
}

function VerifyForm({ initialTab, current }: { initialTab: Tab; current: string }) {
  const params = useSearchParams();
  const router = useRouter();
  const [tab, setTab] = useState<Tab>(initialTab);
  const [input, setInput] = useState(current);
  const [error, setError] = useState<string | null>(null);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const value = input.trim();
    if (!UUID.test(value)) {
      setError("Paste a full ID, for example 29495ccd-1f47-4031-ba3d-d86df4c89a4a.");
      return;
    }
    setError(null);
    router.push(`/verify?${tab}=${value}`);
  };

  const switchTab = (next: Tab) => {
    setTab(next);
    setInput("");
    setError(null);
    router.push("/verify");
  };

  const active = params.get(tab);
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-3xl font-semibold">Verify</h1>
        <p className="mt-1 text-muted">Anyone can check that a question comes from its document and that a quiz was not changed. No login needed.</p>
      </div>
      <div className="inline-flex rounded-lg border border-line bg-card p-1" role="tablist">
        {(["question", "quiz"] as Tab[]).map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            onClick={() => switchTab(t)}
            className={`rounded-md px-4 py-2 text-sm font-semibold capitalize ${tab === t ? "bg-navy text-white" : "text-muted hover:text-ink"}`}
          >
            {t}
          </button>
        ))}
      </div>
      <form onSubmit={submit} className="flex flex-col gap-2 sm:flex-row">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={tab === "question" ? "Question ID" : "Quiz ID"}
          className="min-w-0 flex-1 rounded-lg border border-line bg-white px-3 py-2.5 font-mono text-sm outline-none focus:border-accent"
          aria-label={tab === "question" ? "Question ID" : "Quiz ID"}
        />
        <Button type="submit">Verify</Button>
      </form>
      {error && <ErrorBox message={error} />}
      {active && UUID.test(active) && (tab === "question" ? <QuestionResult key={active} id={active} /> : <QuizResult key={active} id={active} />)}
    </div>
  );
}

export function VerifyView() {
  const authed = useToken() !== null;
  return (
    <Page authed={authed}>
      <Verify />
    </Page>
  );
}
