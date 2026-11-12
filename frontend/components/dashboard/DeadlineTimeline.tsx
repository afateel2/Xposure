"use client";

import Link from "next/link";
import { useMemo } from "react";
import { Bi } from "@/components/Bi";
import { BrandMotif } from "@/components/ui";
import { needsAttention } from "@/lib/review-queue";
import type { ChangeSummaryOut } from "@/lib/types";

/**
 * Deadlines of the work that is still open, grouped by date so that stacked
 * dates read as waves of work. A deadline exists only when the regulator
 * published an effective date (plus any stated grace period); for the NCA
 * editions most changes have none, and the honest answer is to say so, never
 * to invent one (backend/app/agent/graph.py::_due_date).
 */
export function DeadlineTimeline({ changes }: { changes: ChangeSummaryOut[] | null }) {
  const view = useMemo(() => {
    const open = (changes ?? []).filter(needsAttention);
    const dated = open.filter((c) => c.due_date);
    const byDate = new Map<string, ChangeSummaryOut[]>();
    for (const c of dated) {
      const list = byDate.get(c.due_date as string) ?? [];
      list.push(c);
      byDate.set(c.due_date as string, list);
    }
    const waves = [...byDate.entries()].sort(([a], [b]) => a.localeCompare(b));
    return { open: open.length, withDate: dated.length, waves, max: Math.max(1, ...waves.map(([, list]) => list.length)) };
  }, [changes]);

  if (changes === null) return <BrandMotif variant="spinner" compact title={<Bi en="Loading" ar="جارٍ التحميل" />} />;

  if (view.waves.length === 0) {
    return (
      <div className="dl-empty">
        <p className="dl-empty-title">
          <Bi
            en={view.open === 0 ? "No open changes." : "No open change has a published deadline."}
            ar={view.open === 0 ? "لا توجد تغييرات مفتوحة." : "لا يحمل أي تغيير مفتوح موعدًا منشورًا."}
          />
        </p>
        {view.open > 0 && (
          <p className="xp-muted">
            <Bi
              en={`The regulator published no effective date for any of the ${view.open} open changes, so Xposure shows no deadline rather than inventing one. When a date is published, the waves of work appear here.`}
              ar={`لم تنشر الجهة التنظيمية تاريخ سريان لأي من ${view.open} تغييرًا مفتوحًا، لذا لا يعرض Xposure موعدًا بدل أن يخترعه. وعند نشر تاريخ تظهر هنا موجات العمل.`}
            />
          </p>
        )}
      </div>
    );
  }

  const today = new Date().toISOString().slice(0, 10);
  const undated = view.open - view.withDate;
  return (
    <div className="dl">
      <ul className="dl-waves">
        {view.waves.map(([date, list]) => {
          const overdue = date < today;
          return (
            <li key={date} className={overdue ? "is-overdue" : undefined}>
              <bdi className="dl-date tabular">{date}</bdi>
              <span className="dl-bar" aria-hidden="true"><i style={{ inlineSize: `${(list.length / view.max) * 100}%` }} /></span>
              <Link href="/changes" className="dl-count tabular">
                <Bi en={`${list.length} change(s)`} ar={`${list.length} تغيير`} />
              </Link>
              {overdue && <span className="dl-flag"><Bi en="Overdue" ar="متأخر" /></span>}
            </li>
          );
        })}
      </ul>
      {undated > 0 && (
        <p className="xp-muted dl-undated">
          <Bi
            en={`${undated} more open change(s) have no published deadline and are not shown here.`}
            ar={`${undated} تغييرًا مفتوحًا آخر بلا موعد منشور ولا يظهر هنا.`}
          />
        </p>
      )}
    </div>
  );
}
