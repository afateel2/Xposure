"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export interface PollState<T> {
  data: T | null;
  /** Last error, cleared by the next success. The previous data stays in place (no layout shift). */
  error: unknown;
  /** True until the first response (success or failure) arrived. */
  loading: boolean;
  /** True while a refresh is in flight. */
  refreshing: boolean;
  /** Time (ms) of the last successful response, for "data as of". */
  updatedAt: number | null;
  reload: () => void;
}

/**
 * Fetch now, then again every `interval` ms, only while the tab is visible
 * (a hidden tab pauses and refreshes immediately when it comes back). The
 * interval may be a function of the latest data, so a caller can poll every
 * 5 s while the agent is scanning and every 30 s otherwise. Previous data is
 * kept during refreshes and after failures, so nothing jumps.
 * `deps` restarts the loop with a fresh fetch (for example a filter change).
 */
export function usePoll<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  interval: number | ((data: T | null) => number),
  deps: readonly unknown[] = [],
): PollState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const [tick, setTick] = useState(0);

  const fetcherRef = useRef(fetcher);
  const intervalRef = useRef(interval);
  const dataRef = useRef<T | null>(null);
  useEffect(() => {
    fetcherRef.current = fetcher;
    intervalRef.current = interval;
  });

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    let controller: AbortController | undefined;

    const schedule = () => {
      const ms = typeof intervalRef.current === "function" ? intervalRef.current(dataRef.current) : intervalRef.current;
      timer = window.setTimeout(run, ms);
    };

    const run = async () => {
      if (cancelled) return;
      if (document.hidden) {
        // Paused: wait for the tab to come back (see onVisible below).
        return;
      }
      controller = new AbortController();
      setRefreshing(true);
      try {
        const next = await fetcherRef.current(controller.signal);
        if (cancelled) return;
        dataRef.current = next;
        setData(next);
        setError(null);
        setUpdatedAt(Date.now());
      } catch (err) {
        if (cancelled || (err instanceof DOMException && err.name === "AbortError")) return;
        setError(err);
      } finally {
        if (!cancelled) {
          setLoading(false);
          setRefreshing(false);
          schedule();
        }
      }
    };

    const onVisible = () => {
      if (!document.hidden && !cancelled) {
        window.clearTimeout(timer);
        void run();
      }
    };
    document.addEventListener("visibilitychange", onVisible);
    void run();

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      controller?.abort();
      document.removeEventListener("visibilitychange", onVisible);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, ...deps]);

  const reload = useCallback(() => setTick((n) => n + 1), []);
  return { data, error, loading, refreshing, updatedAt, reload };
}
