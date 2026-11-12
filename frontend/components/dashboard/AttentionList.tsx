"use client";

import Link from "next/link";
import { useMemo } from "react";
import { ArrowRight, Timer } from "lucide-react";
import { Bi } from "@/components/Bi";
import { BrandMotif, Icon, PriorityPill } from "@/components/ui";
import type { Priority } from "@/components/ui";
import { getChanges } from "@/lib/api";
import { useLang } from "@/lib/lang";
import { absoluteDate } from "@/lib/time";
import { usePoll } from "@/lib/use-poll";
import type { ChangeSummaryOut, PriorityBand } from "@/lib/types";

const RANK: Record<PriorityBand, number> = { critical: 0, high: 1, medium: 2, low: 3 };
// Same quadrant mapping as the backend (visibility/labels.py BAND_TO_MATRIX_KEY).
const BAND_TO_PILL: Record<PriorityBand, Priority> = { critical: "critical", high: "quick", medium: "strategic", low: "followup" };

function pending(c: ChangeSummaryOut): number {
  return (c.action_status_counts.pending ?? 0) + (c.action_status_counts.awaiting_confirmation ?? 0);
}

/**
 * "Needs your attention": the top open changes by priority (critical first,
 * then overdue, then earliest internal due date, then score), each with its
 * due date and a link to the change. Refetches when `refreshKey` changes so
 * it follows the overview counts without polling the heavy list on its own.
 */
export function AttentionList({ refreshKey, limit = 5 }: { refreshKey: string; limit?: number }) {
  const lang = useLang();
  const { data, error, loading } = usePoll(() => getChanges({ materialOnly: true }), 120_000, [refreshKey]);

  const top = useMemo(() => {
    if (!data) return [];
    return data
      .filter((c) => c.material !== false && pending(c) > 0)
      .sort(
        (a, b) =>
          RANK[a.priority_band] - RANK[b.priority_band] ||
          Number(b.is_overdue) - Number(a.is_overdue) ||
          (a.due_date ?? "9999").localeCompare(b.due_date ?? "9999") ||
          b.priority_score - a.priority_score,
      )
      .slice(0, limit);
  }, [data, limit]);

  if (loading) return <BrandMotif variant="spinner" compact title={<Bi en="Loading" ar="جارٍ التحميل" />} />;
  if (!data) {
    return (
      <BrandMotif
        compact
        title={<Bi en="Changes could not be loaded" ar="تعذّر تحميل التغييرات" />}
        hint={error ? <Bi en="The list will retry automatically." ar="ستُعاد المحاولة تلقائيًا." /> : undefined}
      />
    );
  }
  if (top.length === 0) {
    return (
      <BrandMotif
        compact
        title={<Bi en="Nothing needs your attention" ar="لا يوجد ما يتطلب انتباهك" />}
        hint={<Bi en="No open change is waiting for a decision." ar="لا يوجد تغيير مفتوح بانتظار قرار." />}
      />
    );
  }

  return (
    <ul className="dash-attn">
      {top.map((c) => (
        <li key={c.id}>
          <Link href={`/changes/${c.id}`} className="dash-attn-item">
            <PriorityPill priority={BAND_TO_PILL[c.priority_band]} />
            <span className="dash-attn-main">
              <span className="dash-attn-title"><Bi en={c.summary_en} ar={c.summary_ar} /></span>
              <span className="dash-attn-meta">
                {c.clause_ref && <bdi className="mono">{c.clause_ref}</bdi>}
                <span>
                  <Bi en={`${pending(c)} ${pending(c) === 1 ? "action" : "actions"} open`} ar={`${pending(c)} إجراءً مفتوحًا`} />
                </span>
                {c.due_date ? (
                  <span className={c.is_overdue ? "is-overdue" : ""} title={lang === "ar" ? "الموعد الداخلي" : "Internal due date"}>
                    <Icon icon={Timer} size={12} />
                    <Bi en={`${c.is_overdue ? "Overdue, was due" : "Due"} ${absoluteDate(c.due_date, "en")}`} ar={`${c.is_overdue ? "متأخر، كان موعده" : "الموعد"} ${absoluteDate(c.due_date, "ar")}`} />
                  </span>
                ) : (
                  <span className="dash-nodue"><Bi en="No due date set" ar="بلا موعد محدد" /></span>
                )}
              </span>
            </span>
            <Icon icon={ArrowRight} size={16} flipRtl className="dash-attn-go" />
          </Link>
        </li>
      ))}
    </ul>
  );
}
