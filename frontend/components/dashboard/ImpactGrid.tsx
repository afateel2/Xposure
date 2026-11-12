"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Bi } from "@/components/Bi";
import { BrandMotif, PriorityPill } from "@/components/ui";
import { needsAttention } from "@/lib/review-queue";
import type { ChangeSummaryOut } from "@/lib/types";

/**
 * Where the open work is, on two axes that are always known:
 *
 *   reach     how many items in the organization the change touches
 *   severity  does it raise the bar (a new or tightened obligation) or not
 *
 * Deadline is deliberately not an axis: the regulator publishes no effective
 * date for most changes and Xposure never invents one (see the Deadlines
 * card). Severity is read from the same fixed priority formula the scores use
 * (new_obligation 70, tightened 55, everything else lower), so the grid and
 * the score can never disagree about what "serious" means.
 */
const RAISES_THE_BAR_WEIGHT = 55;
const MAX_LISTED = 8;

type CellKey = "first" | "contained" | "broad" | "monitor";

const CELLS: { key: CellKey; en: string; ar: string; hintEn: string; hintAr: string }[] = [
  { key: "first", en: "Do first", ar: "ابدأ بها أولًا", hintEn: "Raises the bar and reaches widely", hintAr: "ترفع المستوى وتصل إلى نطاق واسع" },
  { key: "contained", en: "Binding but contained", ar: "ملزِمة لكن محدودة", hintEn: "Raises the bar, touches few items", hintAr: "ترفع المستوى وتمسّ عناصر قليلة" },
  { key: "broad", en: "Broad but lighter", ar: "واسعة لكنها أخف", hintEn: "Reaches widely, does not raise the bar", hintAr: "تصل إلى نطاق واسع دون رفع المستوى" },
  { key: "monitor", en: "Monitor", ar: "للمتابعة", hintEn: "Touches few items, does not raise the bar", hintAr: "تمسّ عناصر قليلة دون رفع المستوى" },
];

function median(values: number[]): number {
  if (values.length === 0) return 1;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

export function ImpactGrid({ changes }: { changes: ChangeSummaryOut[] | null }) {
  const [selected, setSelected] = useState<CellKey | null>(null);

  const { cells, cut, total } = useMemo(() => {
    const open = (changes ?? []).filter(needsAttention);
    // "Wide reach" is relative to the open work: at or above its median, and never below 1 item.
    const reachCut = Math.max(1, Math.ceil(median(open.map((c) => c.impacted_node_count))));
    const buckets: Record<CellKey, ChangeSummaryOut[]> = { first: [], contained: [], broad: [], monitor: [] };
    for (const c of open) {
      const raises = c.priority_breakdown.severity_weight >= RAISES_THE_BAR_WEIGHT;
      const wide = c.impacted_node_count >= reachCut;
      buckets[raises ? (wide ? "first" : "contained") : wide ? "broad" : "monitor"].push(c);
    }
    return { cells: buckets, cut: reachCut, total: open.length };
  }, [changes]);

  if (changes === null) return <BrandMotif variant="spinner" compact title={<Bi en="Loading" ar="جارٍ التحميل" />} />;
  if (total === 0) {
    return (
      <BrandMotif
        compact
        title={<Bi en="Nothing open to place" ar="لا يوجد عمل مفتوح لوضعه على الشبكة" />}
        hint={<Bi en="Changes that still need a decision appear here after a scan." ar="تظهر هنا التغييرات التي ما زالت تحتاج إلى قرار بعد الفحص." />}
      />
    );
  }

  const listed = selected ? cells[selected] : [];

  return (
    <div className="ig">
      <p className="ig-axes">
        <span><Bi en="Rows: does it raise the bar (a new or tightened obligation)?" ar="الصفوف: هل ترفع المستوى (التزام جديد أو أشدّ)؟" /></span>
        <span><Bi en={`Columns: wide reach means it touches ${cut} or more items (the median of the open work).`} ar={`الأعمدة: الانتشار الواسع يعني أنها تمسّ ${cut} عنصرًا أو أكثر (وسيط العمل المفتوح).`} /></span>
      </p>

      <div className="ig-grid" role="group" aria-label="Open changes by reach and severity">
        {CELLS.map((cell) => {
          const count = cells[cell.key].length;
          const active = selected === cell.key;
          return (
            <button
              key={cell.key}
              type="button"
              className={`ig-cell ig-${cell.key}${active ? " is-active" : ""}`}
              aria-pressed={active}
              disabled={count === 0}
              onClick={() => setSelected(active ? null : cell.key)}
            >
              <span className="ig-num tabular">{count}</span>
              <span className="ig-name"><Bi en={cell.en} ar={cell.ar} /></span>
              <span className="ig-hint"><Bi en={cell.hintEn} ar={cell.hintAr} /></span>
            </button>
          );
        })}
      </div>

      {selected && (
        <div className="ig-list" aria-live="polite">
          <p className="ig-list-head">
            <b><Bi en={CELLS.find((c) => c.key === selected)!.en} ar={CELLS.find((c) => c.key === selected)!.ar} /></b>
            <span className="tabular"> · <Bi en={`${listed.length} change(s)`} ar={`${listed.length} تغيير`} /></span>
          </p>
          <ul>
            {listed.slice(0, MAX_LISTED).map((c) => (
              <li key={c.id}>
                <PriorityPill band={c.priority_band} />
                <Link href={`/changes/${c.id}`}>
                  <bdi className="mono">{c.clause_ref ?? `#${c.id}`}</bdi>
                  <span className="ig-sum"><Bi en={c.summary_en} ar={c.summary_ar || c.summary_en} /></span>
                </Link>
                <span className="ig-reach tabular"><Bi en={`${c.impacted_node_count} items`} ar={`${c.impacted_node_count} عنصرًا`} /></span>
              </li>
            ))}
          </ul>
          {listed.length > MAX_LISTED && (
            <p className="ig-more">
              <Link href="/changes"><Bi en={`and ${listed.length - MAX_LISTED} more in Changes`} ar={`و${listed.length - MAX_LISTED} أخرى في صفحة التغييرات`} /></Link>
            </p>
          )}
        </div>
      )}
    </div>
  );
}
