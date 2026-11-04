"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";
import type { ChainStatus } from "@/lib/types";

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" };

const BUTTON = {
  primary: "bg-accent text-navy hover:bg-accent-strong hover:text-white",
  secondary: "bg-navy text-white hover:bg-navy-soft",
  ghost: "bg-transparent text-ink border border-line hover:border-ink",
};

export function Button({ variant = "primary", className = "", ...props }: ButtonProps) {
  return (
    <button
      {...props}
      className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${BUTTON[variant]} ${className}`}
    />
  );
}

export function ButtonLink({ href, variant = "primary", children, className = "" }: { href: string; variant?: keyof typeof BUTTON; children: ReactNode; className?: string }) {
  return (
    <Link
      href={href}
      className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold transition-colors ${BUTTON[variant]} ${className}`}
    >
      {children}
    </Link>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-xl border border-line bg-card p-5 sm:p-6 ${className}`}>{children}</section>;
}

export function NavyPanel({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-xl bg-navy p-5 text-white sm:p-6 ${className}`}>{children}</section>;
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <p className="flex items-center gap-3 py-6 text-muted" role="status">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-line border-t-accent" aria-hidden />
      {label}
    </p>
  );
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="rounded-lg border border-bad/30 bg-bad-soft p-4 text-sm text-bad" role="alert">
      <p>{message}</p>
      {onRetry && (
        <button onClick={onRetry} className="mt-2 font-semibold underline underline-offset-2">
          Try again
        </button>
      )}
    </div>
  );
}

/** Visible on every page that shows chain data. Offline is never shown as a failure. */
export function ChainBadge({ status }: { status: ChainStatus }) {
  if (status === "confirmed")
    return <span className="inline-flex items-center gap-1.5 rounded-full bg-ok-soft px-3 py-1 text-xs font-semibold text-ok">● On Polygon Amoy</span>;
  if (status === "pending")
    return <span className="inline-flex items-center gap-1.5 rounded-full bg-paper px-3 py-1 text-xs font-semibold text-muted">○ Chain pending</span>;
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-warn-soft px-3 py-1 text-xs font-semibold text-warn" title="The chain could not be reached or this item is not on chain yet">
      ⚠ Chain offline
    </span>
  );
}

export function shortHash(value: string, head = 10, tail = 8): string {
  return value.length > head + tail + 1 ? `${value.slice(0, head)}…${value.slice(-tail)}` : value;
}

/** Monospace hash, shortened, with a copy button. */
export function Hash({ value, label, dark = false }: { value: string; label?: string; dark?: boolean }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard blocked: the full value is in the title tooltip.
    }
  };
  return (
    <span className="inline-flex max-w-full items-center gap-2">
      {label && <span className={`text-xs ${dark ? "text-white/60" : "text-muted"}`}>{label}</span>}
      <code title={value} className={`truncate rounded px-1.5 py-0.5 font-mono text-xs ${dark ? "bg-white/10 text-white" : "bg-paper text-ink"}`}>
        {shortHash(value)}
      </code>
      <button
        onClick={copy}
        className={`shrink-0 rounded px-1.5 py-0.5 text-xs font-semibold ${dark ? "text-accent hover:text-white" : "text-accent-strong hover:text-ink"}`}
        aria-label={`Copy ${label ?? "hash"}`}
      >
        {copied ? "Copied" : "Copy"}
      </button>
    </span>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="rounded-lg border border-line bg-card p-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted">{label}</p>
      <p className="mt-1 font-display text-2xl font-semibold text-ink">{value}</p>
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </div>
  );
}

export function ExplorerLink({ url, children = "View on Polygon Amoy ↗" }: { url: string | null; children?: ReactNode }) {
  if (!url) return null;
  return (
    <a href={url} target="_blank" rel="noreferrer" className="text-sm font-semibold text-accent-strong underline underline-offset-2 hover:text-ink">
      {children}
    </a>
  );
}
