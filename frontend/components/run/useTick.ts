"use client";

import { useEffect, useState } from "react";

/**
 * A clock for live elapsed timers. Ticks every `ms` only while `active` and
 * the tab is visible (a hidden tab does no work), and cleans up on unmount.
 * Returns the current time in ms.
 */
export function useTick(active: boolean, ms = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    let id: number | undefined;
    const start = () => {
      window.clearInterval(id);
      setNow(Date.now());
      id = window.setInterval(() => setNow(Date.now()), ms);
    };
    const onVis = () => {
      if (document.hidden) window.clearInterval(id);
      else start();
    };
    if (!document.hidden) start();
    document.addEventListener("visibilitychange", onVis);
    return () => {
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [active, ms]);
  return now;
}
