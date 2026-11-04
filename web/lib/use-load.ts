"use client";

import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { getToken } from "./api";

type LoadState<T> = { data: T | null; error: string | null; status: number | null; key: unknown };

/**
 * Loads data when `key` changes; `reload()` fetches again. State is only set from promise callbacks,
 * so no effect sets state synchronously. `data` stays null until the first load finishes.
 */
export function useLoad<T>(fetcher: () => Promise<T>, key: unknown) {
  const [tick, setTick] = useState(0);
  const [state, setState] = useState<LoadState<T>>({ data: null, error: null, status: null, key: undefined });

  useEffect(() => {
    let alive = true;
    fetcher().then(
      (data) => alive && setState({ data, error: null, status: null, key }),
      (e: Error & { status?: number }) => alive && setState({ data: null, error: e.message, status: e.status ?? null, key }),
    );
    return () => {
      alive = false;
    };
    // fetcher is recreated each render; key and tick decide when to load.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  const fresh = state.key === key;
  return {
    data: fresh ? state.data : null,
    error: fresh ? state.error : null,
    status: fresh ? state.status : null,
    reload,
    setData: (data: T) => setState({ data, error: null, status: null, key }),
  };
}

const noopSubscribe = () => () => {};

/** The stored token, or null on the server and before hydration. */
export function useToken(): string | null {
  return useSyncExternalStore(noopSubscribe, getToken, () => null);
}
