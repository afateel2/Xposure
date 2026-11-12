"use client";

import Link from "next/link";
import { ChevronRight, Gauge, Maximize2 } from "lucide-react";
import { affectedNodesAr, CHANGE_TYPE_LABEL } from "@/lib/labels";
import { t, useLang } from "@/lib/lang";
import type { ChangeDetailOut, ChangeSummaryOut } from "@/lib/types";
import { Bi } from "./Bi";
import { ChangeDetailPanel } from "./ChangeDetailPanel";
import { DueLabel } from "./changes/DueLabel";
import { Isolated } from "./changes/Isolated";
import { RelTime } from "./changes/RelTime";
import { Badge, BrandMotif, Icon, PriorityPill } from "./ui";

/** Action status counts as compact status badges (info new/awaiting, warning pending, success done). */
function StatusCounts({ counts }: { counts: ChangeSummaryOut["action_status_counts"] }) {
  const pending = counts.pending ?? 0;
  const awaiting = counts.awaiting_confirmation ?? 0;
  const approved = counts.approved ?? 0;
  const done = counts.done ?? 0;
  const dismissed = counts.dismissed ?? 0;
  if (pending + awaiting + approved + done + dismissed === 0) return null;
  return (
    <span className="chg-row-counts">
      {pending > 0 && <Badge variant="pending"><span className="tabular">{pending}</span> <Bi en="pending" ar="قيد الانتظار" /></Badge>}
      {awaiting > 0 && <Badge variant="new"><span className="tabular">{awaiting}</span> <Bi en="awaiting" ar="بانتظار التأكيد" /></Badge>}
      {approved > 0 && <Badge variant="approved"><span className="tabular">{approved}</span> <Bi en="approved" ar="معتمد" /></Badge>}
      {done > 0 && <Badge variant="approved"><span className="tabular">{done}</span> <Bi en="done" ar="منجز" /></Badge>}
      {dismissed > 0 && <Badge variant="neutral"><span className="tabular">{dismissed}</span> <Bi en="dismissed" ar="مُتجاهَل" /></Badge>}
    </span>
  );
}

export function ChangeRow({
  change,
  expanded,
  onToggle,
  detail,
  detailError,
  isNew = false,
}: {
  change: ChangeSummaryOut;
  expanded: boolean;
  onToggle: () => void;
  detail: ChangeDetailOut | null;
  detailError: string | null;
  /** Created after the reader's last visit: highlighted. */
  isNew?: boolean;
}) {
  const typeLabel = change.change_type ? CHANGE_TYPE_LABEL[change.change_type] : null;
  const lang = useLang();
  const openFullPageLabel = t(lang, "Open as full page", "فتح كصفحة كاملة");
  const n = change.impacted_node_count;

  return (
    <li className={`chg-row${expanded ? " is-open" : ""}${isNew ? " is-new" : ""}${change.is_overdue ? " is-overdue" : ""}`}>
      <div className="chg-row-wrap">
        <button type="button" className="chg-row-btn" aria-expanded={expanded} onClick={onToggle}>
          <span className={`chg-row-stripe ${change.priority_band}`} aria-hidden="true" />
          <span className="chg-row-main">
            <span className="chg-row-top">
              <PriorityPill band={change.priority_band} />
              {isNew && <span title={t(lang, "New since your last visit", "جديد منذ زيارتك الأخيرة")}><Badge variant="new"><Bi en="New" ar="جديد" /></Badge></span>}
              {change.clause_ref && <bdi className="clause-ref">{change.clause_ref}</bdi>}
              {typeLabel && <Badge variant="neutral"><Bi en={typeLabel.en} ar={typeLabel.ar} /></Badge>}
              <span className="chg-row-reg"><bdi>{change.regulator.code.toUpperCase()} {change.regulation.code.toUpperCase()}</bdi></span>
            </span>
            <span className="chg-row-title"><Bi en={change.summary_en} ar={<Isolated text={change.summary_ar} />} /></span>
            <span className="chg-row-sub">
              {n > 0 ? (
                <span className="chg-row-impact">
                  <Bi en={`${n} impacted`} ar={affectedNodesAr(n)} />
                </span>
              ) : (
                <span className="chg-row-impact xp-muted"><Bi en="No impacted nodes" ar="لا عناصر متأثرة" /></span>
              )}
              <StatusCounts counts={change.action_status_counts} />
            </span>
          </span>
          <span className="chg-row-side">
            <DueLabel dueDate={change.due_date ?? change.effective_date} overdue={change.is_overdue} compact />
            {change.confidence != null && (
              <span className="chg-row-conf tabular" title={t(lang, "Model confidence", "ثقة النموذج")}>
                <Icon icon={Gauge} size={13} />
                {Math.round(change.confidence * 100)}%
              </span>
            )}
            <span className="chg-row-when">
              <RelTime value={change.created_at} prefixEn="Detected" prefixAr="رُصد" />
            </span>
          </span>
          <Icon icon={ChevronRight} size={18} flipRtl className="chg-row-chevron" />
        </button>
        <Link href={`/changes/${change.id}`} className="xp-btn xp-btn-secondary xp-btn-sm xp-btn-icon chg-row-open" aria-label={openFullPageLabel} title={openFullPageLabel}>
          <Icon icon={Maximize2} size={15} />
        </Link>
      </div>
      {expanded && (
        <>
          {detailError && (
            <div className="chg-row-detail">
              <p className="xp-error" role="alert">{detailError}</p>
            </div>
          )}
          {!detailError && !detail && <BrandMotif variant="spinner" compact title={<Bi en="Loading..." ar="جارٍ التحميل..." />} />}
          {!detailError && detail && <ChangeDetailPanel key={detail.id} detail={detail} mode="inline" />}
        </>
      )}
    </li>
  );
}
