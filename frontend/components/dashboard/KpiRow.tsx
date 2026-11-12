"use client";

import { ClipboardCheck, FileDiff, Hourglass, ListChecks, OctagonAlert, Timer } from "lucide-react";
import { Bi } from "@/components/Bi";
import { Icon, StatCard } from "@/components/ui";
import type { Overview } from "@/lib/types-visibility";

/**
 * KPI row: counts, not scores. No single "compliance percentage" on purpose
 * (a green number would suggest more than the data can show); remediation is
 * shown as resolved of total actions.
 */
export function KpiRow({ overview }: { overview: Overview | null }) {
  const q = overview?.review_queue;
  const t = overview?.tasks;
  const r = overview?.remediation;
  const dash = "-";
  const num = (n: number | undefined) => (n == null ? dash : n);
  const pct = r && r.total_actions > 0 ? Math.round((r.resolved_actions / r.total_actions) * 100) : null;

  return (
    <div className="dash-kpis" aria-busy={!overview}>
      <StatCard
        href="/changes"
        label={<Bi en="Needs review" ar="بانتظار المراجعة" />}
        value={num(q?.total)}
        trend={q ? <Bi en={`${q.pending_actions} actions waiting`} ar={`${q.pending_actions} إجراءً بانتظار القرار`} /> : " "}
        icon={<Icon icon={FileDiff} size={16} />}
      />
      <StatCard
        href="/changes"
        tone={q && q.critical > 0 ? "critical" : "default"}
        label={<Bi en="Critical" ar="حرجة" />}
        value={num(q?.critical)}
        trend={q ? (q.critical > 0 ? <Bi en="Act this week" ar="تنفيذ خلال هذا الأسبوع" /> : <Bi en="None open" ar="لا يوجد حاليًا" />) : " "}
        icon={<Icon icon={OctagonAlert} size={16} />}
      />
      <StatCard
        href="/tasks?filter=waiting"
        label={<Bi en="Open tasks" ar="مهام مفتوحة" />}
        value={num(t?.open)}
        trend={t ? <Bi en="Delegated, not confirmed" ar="مُسنَدة ولم يُؤكَّد إنجازها" /> : " "}
        icon={<Icon icon={ListChecks} size={16} />}
      />
      <StatCard
        href="/tasks?filter=waiting"
        tone={t && t.due_within_5_days > 0 ? "warning" : "default"}
        label={<Bi en="Due in 5 days" ar="تستحق خلال 5 أيام" />}
        value={num(t?.due_within_5_days)}
        trend={t ? <Bi en="Open tasks only" ar="من المهام المفتوحة" /> : " "}
        icon={<Icon icon={Hourglass} size={16} />}
      />
      <StatCard
        href="/tasks?filter=overdue"
        tone={t && t.overdue > 0 ? "critical" : "default"}
        label={<Bi en="Overdue" ar="متأخرة" />}
        value={num(t?.overdue)}
        trend={t ? (t.overdue > 0 ? <Bi en="Past the internal due date" ar="تجاوزت الموعد الداخلي" /> : <Bi en="None overdue" ar="لا توجد متأخرات" />) : " "}
        icon={<Icon icon={Timer} size={16} />}
      />
      <div className="xp-stat dash-remed">
        <div className="xp-stat-head">
          <span><Bi en="Remediation" ar="التقدم في المعالجة" /></span>
          <Icon icon={ClipboardCheck} size={16} />
        </div>
        <div className="xp-stat-num">
          {r ? r.resolved_actions : dash}
          <small>{r ? `/${r.total_actions}` : ""}</small>
        </div>
        <div
          className="dash-progress"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={r?.total_actions ?? 0}
          aria-valuenow={r?.resolved_actions ?? 0}
          aria-label="Remediation"
        >
          <div className="dash-progress-fill" style={{ width: `${pct ?? 0}%` }} />
        </div>
        <div className="xp-stat-note">
          {r ? (
            r.total_actions === 0
              ? <Bi en="No actions yet" ar="لا توجد إجراءات بعد" />
              : <Bi en={`${r.resolved_actions} of ${r.total_actions} actions resolved`} ar={`${r.resolved_actions} من ${r.total_actions} إجراءً جرت معالجته`} />
          ) : " "}
        </div>
      </div>
    </div>
  );
}
