"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { getToken, setToken } from "@/lib/api";
import { useToken } from "@/lib/use-load";

/** Redirects to /login when there is no token. Returns true once a token is known to exist. */
export function useRequireAuth(): boolean {
  const router = useRouter();
  const token = useToken();
  const [checked, setChecked] = useState(false);
  useEffect(() => {
    // Runs after hydration, when localStorage is readable.
    const id = setTimeout(() => {
      if (!getToken()) router.replace("/login");
      setChecked(true);
    }, 0);
    return () => clearTimeout(id);
  }, [router]);
  return checked && token !== null;
}

export function Header({ authed = true }: { authed?: boolean }) {
  const router = useRouter();
  const logout = () => {
    setToken(null);
    router.push("/login");
  };
  return (
    <header className="bg-navy text-white">
      <div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
        <Link href="/" className="font-display text-lg font-semibold tracking-tight">
          Smart<span className="text-accent">Quiz</span>
        </Link>
        <nav className="flex items-center gap-1 text-sm">
          <Link href="/verify" className="rounded-md px-3 py-2 text-white/80 hover:bg-white/10 hover:text-white">
            Verify
          </Link>
          {authed && (
            <>
              <Link href="/" className="rounded-md px-3 py-2 text-white/80 hover:bg-white/10 hover:text-white">
                Documents
              </Link>
              <button onClick={logout} className="rounded-md px-3 py-2 text-white/80 hover:bg-white/10 hover:text-white">
                Log out
              </button>
            </>
          )}
        </nav>
      </div>
    </header>
  );
}

export function Page({ children, authed = true }: { children: ReactNode; authed?: boolean }) {
  return (
    <>
      <Header authed={authed} />
      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-6 sm:px-6 sm:py-8">{children}</main>
    </>
  );
}

/** Auth-guarded page: renders nothing until the token check has run. */
export function AuthedPage({ children }: { children: ReactNode }) {
  const ok = useRequireAuth();
  return <Page>{ok ? children : null}</Page>;
}
