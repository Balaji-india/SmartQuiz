"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";
import { Button, ChainBadge, ErrorBox, ExplorerLink, Hash } from "@/components/ui";
import type { BadgeOut } from "@/lib/types";

/** One soulbound concept badge: token, holder, hashes, chain state, explorer and Verify links. */
export function BadgeCard({ badge, subtitle, children }: { badge: BadgeOut; subtitle?: ReactNode; children?: ReactNode }) {
  return (
    <li className={`rounded-xl border p-5 ${badge.revoked ? "border-bad/40 bg-bad-soft/40" : "border-line bg-card"}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-widest text-accent-strong">
            Concept badge{badge.token_id !== null && ` · token #${badge.token_id}`}
          </p>
          <h3 className="mt-1 text-lg font-semibold">{badge.concept}</h3>
          {subtitle && <p className="text-sm text-muted">{subtitle}</p>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {badge.revoked && <span className="rounded-full bg-bad px-3 py-1 text-xs font-semibold text-white">Revoked</span>}
          <ChainBadge status={badge.chain_status} />
        </div>
      </div>
      <div className="mt-4 space-y-1.5 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <Hash value={badge.holder_address} label="Holder" />
          <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${badge.custodial ? "bg-paper text-muted" : "bg-ok-soft text-ok"}`}>
            {badge.custodial ? "custodial address" : "your wallet"}
          </span>
        </div>
        <div>
          <Hash value={badge.concept_hash} label="Concept hash" />
        </div>
        <div>
          <Hash value={badge.evidence_hash} label="Evidence hash" />
        </div>
        <p className="text-xs text-muted">Minted {new Date(badge.created_at).toLocaleString()} · soulbound (cannot be transferred)</p>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-4">
        {badge.token_id !== null && (
          <Link
            href={`/verify?badge=${badge.token_id}`}
            className="text-sm font-semibold text-accent-strong underline underline-offset-2 hover:text-ink"
          >
            Verify badge →
          </Link>
        )}
        <ExplorerLink url={badge.explorer_url}>Mint transaction ↗</ExplorerLink>
      </div>
      {children}
    </li>
  );
}

/** Reason field + confirm for an educator revocation. The reason stays off chain; only its hash is signed. */
export function RevokeForm({ what, onRevoke }: { what: string; onRevoke: (reason: string) => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open)
    return (
      <Button variant="ghost" className="min-h-9 px-3 py-1 text-xs text-bad" onClick={() => setOpen(true)}>
        Revoke {what}…
      </Button>
    );

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await onRevoke(reason.trim());
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <div className="mt-3 space-y-2 rounded-lg border border-bad/30 bg-bad-soft/50 p-3">
      <label className="block text-sm font-medium">
        Reason for revoking this {what} (kept off chain; only its hash is signed)
        <input
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          maxLength={500}
          placeholder="e.g. wrong chapter uploaded"
          className="mt-1 w-full rounded-lg border border-line bg-white px-3 py-2 text-sm outline-none focus:border-accent"
        />
      </label>
      <div className="flex flex-wrap items-center gap-2">
        <button
          onClick={submit}
          disabled={busy || reason.trim().length === 0}
          className="inline-flex min-h-9 items-center rounded-lg bg-bad px-3 py-1 text-xs font-semibold text-white disabled:opacity-50"
        >
          {busy ? "Signing and sending…" : `Revoke ${what} on chain`}
        </button>
        <button onClick={() => setOpen(false)} disabled={busy} className="text-xs font-semibold text-muted underline underline-offset-2">
          Cancel
        </button>
      </div>
      {error && <ErrorBox message={error} />}
    </div>
  );
}
