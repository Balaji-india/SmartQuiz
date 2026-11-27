"use client";

import { useState } from "react";
import type { FactOut, SectionOut, SourceOut } from "@/lib/types";

export type FactRef = FactOut & { section: string };

/** idx -> fact with its section heading, from the textbook tree. */
export function factIndex(sections: SectionOut[]): Map<number, FactRef> {
  const out = new Map<number, FactRef>();
  const walk = (list: SectionOut[]) => {
    for (const s of list) {
      for (const f of s.facts) out.set(f.idx, { ...f, section: s.heading });
      walk(s.children);
    }
  };
  walk(sections);
  return out;
}

/** F-numbered Source chips; clicking one shows the fact's text, page and section under the chips. */
export function FactChips({ idxs, facts, label = "Sources" }: { idxs: number[]; facts: Map<number, SourceOut> | null; label?: string }) {
  const [open, setOpen] = useState<number | null>(null);
  if (idxs.length === 0) return null;
  const shown = open === null ? null : facts?.get(open);
  return (
    <div>
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-xs text-muted">{label}</span>
        {idxs.map((idx) => (
          <button
            key={idx}
            onClick={() => setOpen(open === idx ? null : idx)}
            aria-expanded={open === idx}
            className={`rounded-full px-2 py-0.5 font-mono text-xs font-semibold transition-colors ${open === idx ? "bg-accent text-navy" : "bg-paper text-accent-strong hover:bg-warn-soft"}`}
          >
            F{idx}
          </button>
        ))}
      </div>
      {open !== null && (
        <div className="mt-2 rounded-lg border-l-4 border-accent bg-paper px-3 py-2 text-sm">
          {shown ? (
            <>
              <p className="text-xs font-semibold uppercase tracking-wide text-accent-strong">
                Source · F{shown.idx} · p. {shown.page} · {shown.section}
              </p>
              <p className="mt-1">{shown.text}</p>
            </>
          ) : (
            <p className="text-muted">Fact F{open} is not in the loaded textbook.</p>
          )}
        </div>
      )}
    </div>
  );
}
