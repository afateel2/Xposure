"use client";

import { useEffect } from "react";
import { getAgentState, getOverview } from "@/lib/api-visibility";
import { setNavBadge, setNotificationCount, setNotifications, type ShellNotification } from "@/lib/shell";
import { usePoll } from "@/lib/use-poll";
import type { AgentState, Overview } from "@/lib/types-visibility";

interface Snapshot {
  overview: Overview | null;
  agent: AgentState | null;
}

/**
 * Headless: keeps the sidebar badges and the notification bell current.
 * Polls /overview (and /agent/state) every 30 s while the tab is visible.
 * A failed poll leaves the last badges in place instead of clearing them,
 * and a missing route (404) simply leaves the shell empty.
 *
 * The bell follows the alert-fatigue rule: only things that need a human
 * (critical items, decisions waiting, overdue tasks, a failed scan). One
 * entry per kind, never one per clause.
 */
export function ShellFeed() {
  const { data } = usePoll<Snapshot>(
    async (signal) => {
      const [overview, agent] = await Promise.allSettled([getOverview(signal), getAgentState(signal)]);
      if (overview.status === "rejected" && overview.reason instanceof DOMException) throw overview.reason;
      if (overview.status === "rejected" && agent.status === "rejected") throw overview.reason;
      return {
        overview: overview.status === "fulfilled" ? overview.value : null,
        agent: agent.status === "fulfilled" ? agent.value : null,
      };
    },
    30_000,
  );

  useEffect(() => {
    if (!data) return;
    const { overview, agent } = data;
    if (overview) {
      setNavBadge("changes", overview.review_queue.total);
      setNavBadge("tasks", overview.tasks.open);
    }
    const items: ShellNotification[] = [];
    if (agent?.state === "failed") {
      items.push({ id: "agent-failed", en: "The last scan failed. Open Run agent for details.", ar: "تعذّر إكمال آخر فحص. افتح «تشغيل الوكيل» للتفاصيل.", href: "/agent" });
    }
    if (overview) {
      const q = overview.review_queue;
      const t = overview.tasks;
      if (q.critical > 0) {
        items.push({
          id: "critical",
          en: `${q.critical} critical ${q.critical === 1 ? "change needs" : "changes need"} your review`,
          ar: q.critical === 1 ? "تغيير حرج واحد يحتاج إلى مراجعتك" : `${q.critical} تغييرات حرجة تحتاج إلى مراجعتك`,
          href: "/changes",
        });
      }
      if (t.overdue > 0) {
        items.push({
          id: "overdue",
          en: `${t.overdue} overdue ${t.overdue === 1 ? "task" : "tasks"}`,
          ar: t.overdue === 1 ? "مهمة واحدة متأخرة" : `${t.overdue} مهام متأخرة`,
          href: "/tasks?filter=overdue",
        });
      }
      if (q.total > 0) {
        items.push({
          id: "awaiting",
          en: `${q.total} ${q.total === 1 ? "change is" : "changes are"} waiting for a decision`,
          ar: q.total === 1 ? "تغيير واحد بانتظار قرارك" : `${q.total} تغييرات بانتظار قرارك`,
          href: "/changes",
        });
      }
      if (t.open > 0) {
        items.push({
          id: "confirm",
          en: `${t.open} delegated ${t.open === 1 ? "task" : "tasks"} waiting for confirmation`,
          ar: t.open === 1 ? "مهمة مُسنَدة واحدة بانتظار التأكيد" : `${t.open} مهام مُسنَدة بانتظار التأكيد`,
          href: "/tasks?filter=waiting",
        });
      }
    }
    setNotifications(items);
    // One entry per kind; the bell count is simply the number of entries (null = use the list length).
    setNotificationCount(null);
  }, [data]);

  return null;
}
