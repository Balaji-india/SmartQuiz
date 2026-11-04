"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Page } from "@/components/shell";
import { Button, ErrorBox } from "@/components/ui";
import { login, setToken, signup } from "@/lib/api";

const FIELD = "mt-1 w-full rounded-lg border border-line bg-white px-3 py-2.5 text-base text-ink outline-none focus:border-accent";

export function AuthForm({ mode }: { mode: "login" | "signup" }) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const out = mode === "signup" ? await signup(email, password, name) : await login(email, password);
      setToken(out.token);
      router.push("/");
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  };

  const signupMode = mode === "signup";
  return (
    <Page authed={false}>
      <div className="mx-auto grid max-w-4xl gap-6 md:grid-cols-2 md:items-center">
        <div className="rounded-xl bg-navy p-6 text-white sm:p-8">
          <p className="text-xs font-semibold uppercase tracking-widest text-accent">Proof of Grounding</p>
          <h1 className="mt-3 text-3xl font-semibold leading-tight">Quizzes you can trace back to your own notes.</h1>
          <p className="mt-4 text-white/75">
            Every question comes from numbered facts in your document, passes independent checks, and is committed on chain before you start.
          </p>
        </div>
        <form onSubmit={onSubmit} className="rounded-xl border border-line bg-card p-6 sm:p-8">
          <h2 className="text-2xl font-semibold">{signupMode ? "Create your account" : "Log in"}</h2>
          {signupMode && (
            <label className="mt-5 block text-sm font-medium">
              Name
              <input className={FIELD} value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} autoComplete="name" />
            </label>
          )}
          <label className="mt-4 block text-sm font-medium">
            Email
            <input className={FIELD} type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
          </label>
          <label className="mt-4 block text-sm font-medium">
            Password
            <input
              className={FIELD}
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
              maxLength={128}
              autoComplete={signupMode ? "new-password" : "current-password"}
            />
            {signupMode && <span className="mt-1 block text-xs text-muted">At least 8 characters.</span>}
          </label>
          {error && (
            <div className="mt-4">
              <ErrorBox message={error} />
            </div>
          )}
          <Button type="submit" disabled={busy} className="mt-6 w-full">
            {busy ? "Please wait…" : signupMode ? "Sign up" : "Log in"}
          </Button>
          <p className="mt-4 text-center text-sm text-muted">
            {signupMode ? "Already have an account? " : "New to SmartQuiz? "}
            <Link href={signupMode ? "/login" : "/signup"} className="font-semibold text-accent-strong underline underline-offset-2">
              {signupMode ? "Log in" : "Sign up"}
            </Link>
          </p>
        </form>
      </div>
    </Page>
  );
}
