"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { getChanges } from "@/lib/api";
import type { ChangeSummaryOut } from "@/lib/types";

/**
 * The same rule the Changes list uses to decide what still needs a person:
 * a material change with an open (pending or awaiting confirmation) action, or
 * one that is overdue. Shared so the list and the review queue never disagree.
 */
export function needsAttention(change: ChangeSummaryOut): boolean {
  const pending = change.action_status_counts.pending ?? 0;
  const awaiting = change.action_status_counts.awaiting_confirmation ?? 0;
  return change.material === true && (pending > 0 || awaiting > 0 || change.is_overdue);
}

export interface ReviewQueue {
  status: "loading" | "ready" | "error";
  /** How many changes needed a decision when this page opened. */
  total: number;
  /** 1-based place of the current change in that list, or null when it is not in it. */
  position: number | null;
  /** Changes in the list not yet fully decided here (the current one counts while it still has pending actions). */
  remaining: number;
  /** Neighbours in the list's own order (priority, then id), skipping changes already decided in this visit. */
  prevId: number | null;
  nextId: number | null;
  /** Tell the queue the current change has no pending actions left (or has some again after an undo). */
  markResolved: (changeId: number, resolved: boolean) => void;
}

/**
 * Review is sequential work: after one change the reviewer wants the next one,
 * not the list. The order is the Changes list's own order, loaded once for the
 * page's lifetime (it survives moving between changes).
 */
export function useReviewQueue(currentId: number): ReviewQueue {
  const [all, setAll] = useState<ChangeSummaryOut[] | null>(null);
  const [error, setError] = useState(false);
  const [resolved, setResolved] = useState<Record<number, boolean>>({});

  useEffect(() => {
    let cancelled = false;
    getChanges({ materialOnly: true })
      .then((rows) => {
        if (!cancelled) setAll(rows);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const markResolved = useCallback((changeId: number, value: boolean) => {
    setResolved((prev) => (!!prev[changeId] === value ? prev : { ...prev, [changeId]: value }));
  }, []);

  return useMemo<ReviewQueue>(() => {
    if (error) return { status: "error", total: 0, position: null, remaining: 0, prevId: null, nextId: null, markResolved };
    if (!all) return { status: "loading", total: 0, position: null, remaining: 0, prevId: null, nextId: null, markResolved };

    const attention = all.filter(needsAttention).map((c) => c.id);
    const live = new Set(attention.filter((id) => !resolved[id]));
    const index = all.findIndex((c) => c.id === currentId);

    let prevId: number | null = null;
    let nextId: number | null = null;
    if (index === -1) {
      // The current change is not in the material list (opened by link): start the queue from its top.
      nextId = all.find((c) => live.has(c.id) && c.id !== currentId)?.id ?? null;
    } else {
      for (let i = index + 1; i < all.length; i++) {
        if (live.has(all[i].id) && all[i].id !== currentId) {
          nextId = all[i].id;
          break;
        }
      }
      for (let i = index - 1; i >= 0; i--) {
        if (live.has(all[i].id) && all[i].id !== currentId) {
          prevId = all[i].id;
          break;
        }
      }
    }

    const at = attention.indexOf(currentId);
    return {
      status: "ready",
      total: attention.length,
      position: at === -1 ? null : at + 1,
      remaining: live.size,
      prevId,
      nextId,
      markResolved,
    };
  }, [all, error, resolved, currentId, markResolved]);
}
