"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useLoad } from "@/lib/use-load";
import { AuthedPage } from "@/components/shell";
import { Card, ErrorBox, Loading, Stat } from "@/components/ui";
import { getMetrics } from "@/lib/api";
import type { MetricsOut } from "@/lib/types";

const GATE_LABEL: Record<string, string> = {
  gate1: "Gate 1 · grounding",
  gate3: "Gate 3 · solvability",
  generator_error: "Malformed output",
};

function Bar({ label, value, max, tone }: { label: string; value: number; max: number; tone: "ok" | "bad" }) {
  const pct = max ? Math.max(2, Math.round((100 * value) / max)) : 0;
  return (
    <div>
      <div className="flex justify-between text-sm">
        <span>{label}</span>
        <span className="font-semibold tabular-nums">{value}</span>
      </div>
      <div className="mt-1 h-2.5 rounded-full bg-paper">
        <div className={`h-full rounded-full ${tone === "ok" ? "bg-ok" : "bg-accent"}`} style={{ width: value ? `${pct}%` : "0%" }} />
      </div>
    </div>
  );
}

function Metrics() {
  const { id } = useParams<{ id: string }>();
  const { data: m, error, reload } = useLoad<MetricsOut>(() => getMetrics(id), id);

  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!m) return <Loading label="Loading metrics…" />;

  const rejected = Object.values(m.rejected_by_gate).reduce((a, b) => a + b, 0);
  const max = Math.max(m.accepted, ...Object.values(m.rejected_by_gate), 1);
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-3xl font-semibold">Verification metrics</h1>
          <p className="mt-1 text-muted">Every candidate question and why it was kept or rejected.</p>
        </div>
        <Link href={`/documents/${id}`} className="text-sm font-semibold text-accent-strong underline underline-offset-2">
          ← Back to textbook
        </Link>
      </div>

      {m.same_family_checker_used && (
        <div className="rounded-lg border border-warn/40 bg-warn-soft p-4 text-warn" role="alert">
          <p className="font-semibold">Emergency fallback: same-family checker used for {m.same_family_gate_calls} gate calls</p>
          <p className="mt-1 text-sm">The checker model was from the same family as the generator, so those checks are less independent.</p>
        </div>
      )}

      {m.candidates === 0 ? (
        <Card>
          <p className="text-muted">No quiz has been generated for this document yet.</p>
        </Card>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Candidates" value={m.candidates} hint="questions written" />
            <Stat label="Accepted" value={m.accepted} hint={`${rejected} rejected by gates`} />
            <Stat
              label="Avg dependence"
              value={m.avg_dependence === null ? "—" : m.avg_dependence.toFixed(2)}
              hint="1 = needs your notes, 0 = general knowledge"
            />
            <Stat label="Repeat rate" value={`${Math.round(m.repeat_rate_between_quizzes * 100)}%`} hint="target facts reused across quizzes" />
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <h2 className="text-lg font-semibold">Accepted vs rejected</h2>
              <div className="mt-4 space-y-4">
                <Bar label="Accepted" value={m.accepted} max={max} tone="ok" />
                {Object.entries(m.rejected_by_gate).map(([gate, n]) => (
                  <Bar key={gate} label={`Rejected · ${GATE_LABEL[gate] ?? gate}`} value={n} max={max} tone="bad" />
                ))}
              </div>
              <dl className="mt-6 grid grid-cols-3 gap-3 border-t border-line pt-4 text-sm">
                <div>
                  <dt className="text-muted">Duplicate facts</dt>
                  <dd className="font-display text-xl font-semibold">{m.duplicates_blocked.fingerprint}</dd>
                </div>
                <div>
                  <dt className="text-muted">Near-duplicate stems</dt>
                  <dd className="font-display text-xl font-semibold">{m.duplicates_blocked.cosine}</dd>
                </div>
                <div>
                  <dt className="text-muted">Flagged general</dt>
                  <dd className="font-display text-xl font-semibold">{m.flagged_general}</dd>
                </div>
              </dl>
            </Card>
            <Card>
              <h2 className="text-lg font-semibold">Top rejection reasons</h2>
              {m.top_reasons.length === 0 ? (
                <p className="mt-3 text-sm text-muted">No question has been rejected yet.</p>
              ) : (
                <ul className="mt-3 space-y-3">
                  {m.top_reasons.map((r, i) => (
                    <li key={i} className="rounded-lg bg-paper p-3 text-sm">
                      <p className="text-xs font-semibold uppercase tracking-wide text-accent-strong">
                        {GATE_LABEL[r.gate] ?? r.gate} · ×{r.count}
                      </p>
                      <p className="mt-1">{r.reason}</p>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
        </>
      )}
    </div>
  );
}

export function MetricsView() {
  return (
    <AuthedPage>
      <Metrics />
    </AuthedPage>
  );
}
