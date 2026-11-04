"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { Fragment, useEffect, useRef, useState, type FormEvent } from "react";
import { AuthedPage } from "@/components/shell";
import { Button, ErrorBox } from "@/components/ui";
import { sendChat } from "@/lib/api";
import type { ChatOut } from "@/lib/types";

type Turn = { question: string; reply: ChatOut | null; error?: string };
type Citation = ChatOut["citations"][number];

/** Splits an answer into text and [F214] chips. Unknown refs stay as plain text. */
function AnswerText({ answer, citations, onOpen }: { answer: string; citations: Citation[]; onOpen: (c: Citation) => void }) {
  const byIdx = new Map(citations.map((c) => [c.idx, c]));
  const parts = answer.split(/(\[[^\[\]]*\])/g);
  return (
    <p className="leading-relaxed">
      {parts.map((part, i) => {
        const refs = part.startsWith("[") ? [...part.matchAll(/F(\d+)/g)].map((m) => Number(m[1])) : [];
        if (!refs.length || !refs.every((r) => byIdx.has(r))) return <Fragment key={i}>{part}</Fragment>;
        return (
          <Fragment key={i}>
            {refs.map((r) => (
              <button
                key={r}
                onClick={() => onOpen(byIdx.get(r)!)}
                className="mx-0.5 inline-flex items-center rounded-md bg-navy px-1.5 py-0.5 align-baseline font-mono text-xs font-semibold text-white hover:bg-accent hover:text-navy"
                aria-label={`Open fact ${r}`}
              >
                F{r}
              </button>
            ))}
          </Fragment>
        );
      })}
    </p>
  );
}

function Chat() {
  const { id } = useParams<{ id: string }>();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<Citation | null>(null);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);

  const ask = async (e: FormEvent) => {
    e.preventDefault();
    const question = message.trim();
    if (!question || busy) return;
    setMessage("");
    setBusy(true);
    setTurns((t) => [...t, { question, reply: null }]);
    try {
      const reply = await sendChat(id, question);
      setTurns((t) => t.map((turn, k) => (k === t.length - 1 ? { question, reply } : turn)));
    } catch (err) {
      setTurns((t) => t.map((turn, k) => (k === t.length - 1 ? { question, reply: null, error: (err as Error).message } : turn)));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_300px]">
      <div className="flex min-h-[60vh] flex-col rounded-xl border border-line bg-card">
        <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-4">
          <div>
            <h1 className="text-xl font-semibold">Ask a doubt</h1>
            <p className="text-sm text-muted">Answers come only from your notes, with the facts they use.</p>
          </div>
          <Link href={`/documents/${id}`} className="shrink-0 text-sm font-semibold text-accent-strong underline underline-offset-2">
            Textbook
          </Link>
        </div>
        <div className="flex-1 space-y-5 overflow-y-auto px-5 py-5">
          {turns.length === 0 && (
            <p className="text-muted">Try “Why did the Target breach go unnoticed?” or ask something your notes do not cover.</p>
          )}
          {turns.map((t, i) => (
            <div key={i} className="space-y-3">
              <div className="ml-auto max-w-[85%] rounded-xl rounded-br-sm bg-navy px-4 py-3 text-white">{t.question}</div>
              {!t.reply && !t.error && <p className="text-sm text-muted">Looking through your facts…</p>}
              {t.error && <ErrorBox message={t.error} />}
              {t.reply && !t.reply.abstained && (
                <div className="max-w-[90%] rounded-xl rounded-bl-sm border border-line bg-paper px-4 py-3">
                  <AnswerText answer={t.reply.answer} citations={t.reply.citations} onOpen={setOpen} />
                </div>
              )}
              {t.reply && t.reply.abstained && (
                <div className="max-w-[90%] rounded-xl rounded-bl-sm border border-dashed border-line px-4 py-3 text-muted">
                  <p className="font-medium">This isn’t covered in your material.</p>
                  {t.reply.nearest_sections.length > 0 && (
                    <p className="mt-2 text-sm">
                      Nearest sections:{" "}
                      {t.reply.nearest_sections.map((s, k) => (
                        <Fragment key={s.id}>
                          {k > 0 && " · "}
                          <Link href={`/documents/${id}?section=${s.id}`} className="font-semibold text-accent-strong underline underline-offset-2">
                            {s.heading}
                          </Link>
                        </Fragment>
                      ))}
                    </p>
                  )}
                </div>
              )}
            </div>
          ))}
          <div ref={end} />
        </div>
        <form onSubmit={ask} className="flex gap-2 border-t border-line p-3">
          <input
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            maxLength={1000}
            placeholder="Ask about your notes…"
            className="min-w-0 flex-1 rounded-lg border border-line px-3 py-2.5 text-base outline-none focus:border-accent"
            aria-label="Your question"
          />
          <Button type="submit" disabled={busy || !message.trim()}>
            Ask
          </Button>
        </form>
      </div>
      <aside className="lg:sticky lg:top-6 lg:self-start">
        <div className="rounded-xl border border-line bg-card p-5">
          <h2 className="text-lg font-semibold">Cited fact</h2>
          {open ? (
            <div className="mt-3 space-y-2">
              <p className="font-mono text-xs text-accent-strong">
                F{open.idx} · page {open.page}
              </p>
              <p className="leading-relaxed">{open.text}</p>
            </div>
          ) : (
            <p className="mt-2 text-sm text-muted">Click a fact chip in an answer to read the fact and its page.</p>
          )}
        </div>
      </aside>
    </div>
  );
}

export function ChatView() {
  return (
    <AuthedPage>
      <Chat />
    </AuthedPage>
  );
}
