"use client";

import { useEffect, useState } from "react";
import { getHealth, type Health } from "@/lib/api";

export default function Home() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch((e: Error) => setError(e.message));
  }, []);

  return (
    <main className="mx-auto max-w-xl p-8">
      <h1 className="text-3xl font-semibold">SmartQuiz</h1>
      <p className="mt-4">
        {error && `API unreachable: ${error}`}
        {!error && !health && "Checking the API…"}
        {health && `API ok: ${health.ok} · Database ok: ${health.db}`}
      </p>
    </main>
  );
}
