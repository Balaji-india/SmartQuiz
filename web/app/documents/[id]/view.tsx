"use client";

import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { useLoad } from "@/lib/use-load";
import { AuthedPage } from "@/components/shell";
import { Button, ButtonLink, ChainBadge, ErrorBox, Hash, Loading, NavyPanel } from "@/components/ui";
import { createQuiz, getTextbook, registerDocument } from "@/lib/api";
import type { FactOut, SectionOut, TextbookOut } from "@/lib/types";

function countFacts(s: SectionOut): number {
  return s.facts.length + s.children.reduce((n, c) => n + countFacts(c), 0);
}

function SectionNode({
  section,
  selected,
  onSelect,
  open,
  toggle,
}: {
  section: SectionOut;
  selected: number | null;
  onSelect: (f: FactOut) => void;
  open: Set<number>;
  toggle: (id: number) => void;
}) {
  const isOpen = open.has(section.id);
  const total = countFacts(section);
  return (
    <li id={`section-${section.id}`} className="scroll-mt-20">
      <button
        onClick={() => toggle(section.id)}
        className="flex w-full items-start gap-2 rounded-lg px-2 py-2 text-left hover:bg-paper"
        aria-expanded={isOpen}
      >
        <span className={`mt-0.5 inline-block w-4 text-muted transition-transform ${isOpen ? "rotate-90" : ""}`} aria-hidden>
          ›
        </span>
        <span className="min-w-0 flex-1">
          <span className="font-medium">{section.heading}</span>
          <span className="ml-2 text-xs text-muted">
            p. {section.page_start}
            {section.page_end !== section.page_start ? `–${section.page_end}` : ""} · {total} facts
          </span>
        </span>
      </button>
      {isOpen && (
        <div className="ml-6 border-l border-line pl-3">
          {section.facts.length > 0 && (
            <ul className="space-y-1 py-1">
              {section.facts.map((f) => (
                <li key={f.idx}>
                  <button
                    onClick={() => onSelect(f)}
                    className={`w-full rounded-md px-2 py-1.5 text-left text-sm ${selected === f.idx ? "bg-warn-soft text-ink" : "text-ink/85 hover:bg-paper"}`}
                  >
                    <span className="mr-2 font-mono text-xs text-accent-strong">F{f.idx}</span>
                    {f.text}
                  </button>
                </li>
              ))}
            </ul>
          )}
          {section.children.length > 0 && (
            <ul>
              {section.children.map((c) => (
                <SectionNode key={c.id} section={c} selected={selected} onSelect={onSelect} open={open} toggle={toggle} />
              ))}
            </ul>
          )}
        </div>
      )}
    </li>
  );
}

function Textbook() {
  const { id } = useParams<{ id: string }>();
  const focus = useSearchParams().get("section");
  const router = useRouter();
  const { data: book, error, reload: load, setData: setBook } = useLoad<TextbookOut>(() => getTextbook(id), id);
  const [fact, setFact] = useState<FactOut | null>(null);
  const [open, setOpen] = useState<Set<number>>(new Set());
  const [starting, setStarting] = useState(false);
  const [registering, setRegistering] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  // ?section=<id> (from chat "nearest sections") opens and scrolls to that section.
  useEffect(() => {
    if (!book || !focus) return;
    const target = Number(focus);
    const timer = setTimeout(() => {
      setOpen((prev) => new Set(prev).add(target));
      setTimeout(() => document.getElementById(`section-${target}`)?.scrollIntoView({ behavior: "smooth" }), 50);
    }, 0);
    return () => clearTimeout(timer);
  }, [book, focus]);

  const toggle = (sid: number) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(sid)) next.delete(sid);
      else next.add(sid);
      return next;
    });

  const start = async () => {
    setStarting(true);
    setActionError(null);
    try {
      const quiz = await createQuiz(id, 10, 600);
      router.push(`/quiz/${quiz.id}`);
    } catch (e) {
      setActionError((e as Error).message);
      setStarting(false);
    }
  };

  const retryRegister = async () => {
    setRegistering(true);
    setActionError(null);
    try {
      const doc = await registerDocument(id);
      if (book) setBook({ ...book, document: doc });
    } catch (e) {
      setActionError((e as Error).message);
    } finally {
      setRegistering(false);
    }
  };

  if (error) return <ErrorBox message={error} onRetry={load} />;
  if (!book) return <Loading label="Loading the textbook…" />;
  const doc = book.document;

  return (
    <div className="space-y-6">
      <NavyPanel>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-widest text-accent">Textbook</p>
            <h1 className="mt-1 break-words text-2xl font-semibold sm:text-3xl">{doc.filename}</h1>
          </div>
          <ChainBadge status={doc.chain_status} />
        </div>
        <dl className="mt-5 grid grid-cols-2 gap-4 sm:grid-cols-4">
          {[
            ["Sections", doc.sections_count],
            ["Facts", doc.fact_count],
            ["Quotes not found", doc.facts_dropped],
            ["Rejected as unfaithful", doc.facts_unfaithful],
          ].map(([label, value]) => (
            <div key={label as string}>
              <dt className="text-xs text-white/60">{label}</dt>
              <dd className="font-display text-2xl font-semibold">{value}</dd>
            </div>
          ))}
        </dl>
        <div className="mt-5 flex flex-col gap-2 border-t border-white/10 pt-4 sm:flex-row sm:flex-wrap sm:items-center sm:gap-4">
          {doc.fact_root && <Hash value={doc.fact_root} label="Merkle root" dark />}
          {doc.register_tx && doc.explorer_url && (
            <a href={doc.explorer_url} target="_blank" rel="noreferrer" className="text-sm font-semibold text-accent underline underline-offset-2 hover:text-white">
              View on Polygon Amoy ↗
            </a>
          )}
          {doc.register_tx && !doc.explorer_url && <Hash value={doc.register_tx} label="Registration tx" dark />}
          {doc.chain_status === "offline" && (
            <button onClick={retryRegister} disabled={registering} className="text-sm font-semibold text-accent underline underline-offset-2 disabled:opacity-50">
              {registering ? "Registering…" : "Retry chain registration"}
            </button>
          )}
        </div>
      </NavyPanel>

      <div className="flex flex-wrap gap-3">
        <Button onClick={start} disabled={starting}>
          {starting ? "Creating quiz…" : "Start quiz · 10 questions, 10 min"}
        </Button>
        <ButtonLink href={`/documents/${id}/chat`} variant="secondary">
          Ask a doubt
        </ButtonLink>
        <ButtonLink href={`/documents/${id}/metrics`} variant="ghost">
          Metrics
        </ButtonLink>
      </div>
      {actionError && <ErrorBox message={actionError} />}

      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
        <section className="rounded-xl border border-line bg-card p-3 sm:p-4">
          <div className="flex items-center justify-between px-2 pb-2">
            <h2 className="text-lg font-semibold">Sections</h2>
            <button
              className="text-sm font-semibold text-accent-strong"
              onClick={() => setOpen((prev) => (prev.size ? new Set() : new Set(allIds(book.sections))))}
            >
              {open.size ? "Collapse all" : "Expand all"}
            </button>
          </div>
          <ul>
            {book.sections.map((s) => (
              <SectionNode key={s.id} section={s} selected={fact?.idx ?? null} onSelect={setFact} open={open} toggle={toggle} />
            ))}
          </ul>
        </section>
        <aside className="lg:sticky lg:top-6 lg:self-start">
          <div className="rounded-xl border border-line bg-card p-5">
            <h2 className="text-lg font-semibold">Fact</h2>
            {fact ? (
              <div className="mt-3 space-y-3">
                <p className="font-mono text-xs text-accent-strong">F{fact.idx}</p>
                <p className="text-base leading-relaxed">{fact.text}</p>
                <dl className="grid grid-cols-2 gap-2 text-sm">
                  <dt className="text-muted">Page</dt>
                  <dd>{fact.page}</dd>
                  <dt className="text-muted">Concept</dt>
                  <dd>{fact.concept}</dd>
                </dl>
              </div>
            ) : (
              <p className="mt-2 text-sm text-muted">Open a section and click a fact to see its page and concept.</p>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}

function allIds(sections: SectionOut[]): number[] {
  return sections.flatMap((s) => [s.id, ...allIds(s.children)]);
}

export function DocumentView() {
  return (
    <AuthedPage>
      <Textbook />
    </AuthedPage>
  );
}
