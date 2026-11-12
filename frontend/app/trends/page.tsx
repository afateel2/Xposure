"use client";

import { useEffect, useMemo, useState } from "react";
import { Info, TrendingUp } from "lucide-react";
import { Bi } from "@/components/Bi";
import { BrandMotif, Card, DataTable, Field, Icon, PageHeader, PriorityPill, Segmented } from "@/components/ui";
import type { Priority } from "@/components/ui";
import { getTrends } from "@/lib/api";
import { CHANGE_TYPE_LABEL } from "@/lib/labels";
import { useLang } from "@/lib/lang";
import type { PriorityBand, TrendPointOut } from "@/lib/types";

// Stacked bottom-to-top by severity (most severe grounded at the baseline).
// Colours are the design system's fixed status colours and the band names
// match the dashboard priority matrix and the priority pills, so a colour
// means the same thing on every screen. Every band is also named in the
// legend and in the breakdown table, so colour is never the only signal.
const BAND_ORDER: PriorityBand[] = ["critical", "high", "medium", "low"];
const BAND_PILL: Record<PriorityBand, Priority> = { critical: "critical", high: "quick", medium: "strategic", low: "followup" };
const BAND_VAR: Record<PriorityBand, string> = {
  critical: "var(--danger)", high: "var(--info)", medium: "var(--warning)", low: "var(--ink-muted)",
};
const BAND_LABEL: Record<PriorityBand, { en: string; ar: string }> = {
  critical: { en: "Critical", ar: "حرج" },
  high: { en: "Quick action", ar: "إجراء سريع" },
  medium: { en: "Strategic", ar: "استراتيجي" },
  low: { en: "Follow-up", ar: "متابعة" },
};

const CHART_HEIGHT = 240;
const BAR_WIDTH = 64;
const BAR_GAP = 36;
const SEGMENT_GAP = 2; // surface gap between stacked segments

export default function TrendsPage() {
  const lang = useLang();
  const [rows, setRows] = useState<TrendPointOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [regulatorFilter, setRegulatorFilter] = useState<string>("all");

  useEffect(() => {
    getTrends()
      .then(setRows)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  const regulators = useMemo(() => Array.from(new Set((rows ?? []).map((r) => r.regulator_code))).sort(), [rows]);

  const filtered = useMemo(
    () => (rows ?? []).filter((r) => regulatorFilter === "all" || r.regulator_code === regulatorFilter),
    [rows, regulatorFilter],
  );

  // period -> band -> count, summed across regulation and change type (the
  // table below keeps that full breakdown; the chart shows the headline shape).
  const byPeriod = useMemo(() => {
    const map = new Map<string, Record<PriorityBand, number>>();
    for (const row of filtered) {
      if (!map.has(row.period)) map.set(row.period, { critical: 0, high: 0, medium: 0, low: 0 });
      map.get(row.period)![row.band] += row.count;
    }
    return Array.from(map.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([period, counts]) => ({ period, counts, total: BAND_ORDER.reduce((sum, b) => sum + counts[b], 0) }));
  }, [filtered]);

  const monthLabel = (period: string): string => {
    const [year, month] = period.split("-").map(Number);
    return new Date(year, month - 1, 1).toLocaleDateString(lang === "ar" ? "ar-SA-u-nu-latn-ca-gregory" : "en-GB", { month: "short", year: "numeric" });
  };
  const bandName = (b: PriorityBand) => BAND_LABEL[b][lang];

  const maxTotal = Math.max(1, ...byPeriod.map((p) => p.total));
  const chartWidth = Math.max(320, byPeriod.length * (BAR_WIDTH + BAR_GAP) + BAR_GAP);
  const grandTotal = byPeriod.reduce((s, p) => s + p.total, 0);
  const summary = byPeriod.map((p) => `${monthLabel(p.period)}: ${p.total}`).join(", ");

  return (
    <main>
      <PageHeader
        title={<Bi en="Trends" ar="الاتجاهات" />}
        subtitle={<Bi en="Regulatory change volume over time, by priority." ar="حجم التغييرات التنظيمية عبر الزمن بحسب الأولوية." />}
        actions={
          regulators.length > 1 ? (
            <Field label={<Bi en="Regulator" ar="الجهة التنظيمية" />} htmlFor="trend-reg">
              <Segmented
                value={regulatorFilter}
                onChange={setRegulatorFilter}
                ariaLabel="Regulator"
                options={[{ value: "all", label: <Bi en="All" ar="الكل" /> }, ...regulators.map((c) => ({ value: c, label: <bdi>{c.toUpperCase()}</bdi> }))]}
              />
            </Field>
          ) : undefined
        }
      />

      {error && (
        <Card className="xp-error-card">
          <Bi en="Could not load the trends." ar="تعذّر تحميل بيانات الاتجاهات." /> <bdi className="mono">{error}</bdi>
        </Card>
      )}
      {!error && rows === null && <Card><BrandMotif variant="spinner" title={<Bi en="Loading" ar="جارٍ التحميل" />} /></Card>}
      {!error && rows !== null && byPeriod.length === 0 && (
        <Card>
          <BrandMotif
            title={<Bi en="No classified changes to chart yet" ar="لا توجد تغييرات مصنَّفة لرسمها بعد" />}
            hint={<Bi en="The chart fills in once the agent has compared two versions of a regulation." ar="يمتلئ الرسم عندما يقارن الوكيل بين إصدارين من نظام واحد." />}
          />
        </Card>
      )}

      {!error && byPeriod.length > 0 && (
        <>
          <Card
            title={<Bi en="Changes per month" ar="التغييرات في كل شهر" />}
            icon={<Icon icon={TrendingUp} size={18} />}
            actions={<span className="xp-muted tabular"><Bi en={`${grandTotal} in total`} ar={`الإجمالي ${grandTotal}`} /></span>}
          >
            <ul className="trd-legend">
              {BAND_ORDER.map((band) => (
                <li key={band}>
                  <i style={{ background: BAND_VAR[band] }} aria-hidden="true" />
                  <Bi en={BAND_LABEL[band].en} ar={BAND_LABEL[band].ar} />
                </li>
              ))}
            </ul>

            {/* Time runs left to right in both languages, like the numerals on the axis. */}
            <div className="trd-chart" dir="ltr">
              <svg width={chartWidth} height={CHART_HEIGHT + 40} role="img" aria-label={`${bandName("critical")}, ${bandName("high")}, ${bandName("medium")}, ${bandName("low")}. ${summary}`}>
                {byPeriod.map((point, i) => {
                  const x = BAR_GAP + i * (BAR_WIDTH + BAR_GAP);
                  let yCursor = CHART_HEIGHT;
                  const nonZero = BAND_ORDER.filter((b) => point.counts[b] > 0);
                  const topBand = nonZero[nonZero.length - 1];
                  return (
                    <g key={point.period}>
                      {BAND_ORDER.map((band) => {
                        const count = point.counts[band];
                        if (count === 0) return null;
                        const segHeight = Math.max(2, (count / maxTotal) * (CHART_HEIGHT - 28) - SEGMENT_GAP);
                        const y = yCursor - segHeight;
                        yCursor = y - SEGMENT_GAP;
                        return (
                          <rect key={band} x={x} y={y} width={BAR_WIDTH} height={segHeight} fill={BAND_VAR[band]} rx={band === topBand ? 4 : 0}>
                            <title>{`${monthLabel(point.period)}: ${bandName(band)} ${count}`}</title>
                          </rect>
                        );
                      })}
                      <text x={x + BAR_WIDTH / 2} y={CHART_HEIGHT - (point.total / maxTotal) * (CHART_HEIGHT - 28) - 8} textAnchor="middle" fontSize="12" fontWeight="700" fill="var(--ink)" className="tabular">
                        {point.total}
                      </text>
                      <text x={x + BAR_WIDTH / 2} y={CHART_HEIGHT + 22} textAnchor="middle" fontSize="12" fill="var(--ink-muted)">
                        {monthLabel(point.period)}
                      </text>
                    </g>
                  );
                })}
                <line x1={0} y1={CHART_HEIGHT} x2={chartWidth} y2={CHART_HEIGHT} stroke="var(--border)" strokeWidth={1} />
              </svg>
            </div>
          </Card>

          <h2 className="xp-section-title"><Bi en="Full breakdown" ar="التفصيل الكامل" /></h2>
          <DataTable caption={<Bi en="Full breakdown" ar="التفصيل الكامل" />}>
            <thead>
              <tr>
                <th><Bi en="Month" ar="الشهر" /></th>
                <th><Bi en="Regulator" ar="الجهة التنظيمية" /></th>
                <th><Bi en="Regulation" ar="النظام" /></th>
                <th><Bi en="Change type" ar="نوع التغيير" /></th>
                <th><Bi en="Priority" ar="الأولوية" /></th>
                <th className="num"><Bi en="Count" ar="العدد" /></th>
              </tr>
            </thead>
            <tbody>
              {filtered
                .slice()
                .sort((a, b) => b.period.localeCompare(a.period) || BAND_ORDER.indexOf(a.band) - BAND_ORDER.indexOf(b.band))
                .map((row, i) => (
                  <tr key={`${row.period}-${row.regulator_code}-${row.regulation_code}-${row.change_type}-${row.band}-${i}`}>
                    <td className="mono">{row.period}</td>
                    <td><bdi>{row.regulator_code.toUpperCase()}</bdi></td>
                    <td><bdi>{row.regulation_code.toUpperCase()}</bdi></td>
                    <td>{CHANGE_TYPE_LABEL[row.change_type] ? <Bi en={CHANGE_TYPE_LABEL[row.change_type].en} ar={CHANGE_TYPE_LABEL[row.change_type].ar} /> : <bdi>{row.change_type}</bdi>}</td>
                    <td><PriorityPill priority={BAND_PILL[row.band]} /></td>
                    <td className="num">{row.count}</td>
                  </tr>
                ))}
            </tbody>
          </DataTable>
        </>
      )}

      <p className="trd-note">
        <Icon icon={Info} size={14} />
        <span>
          <Bi
            en="Priority bands here use a simplified organizational-reach factor (not the per-change impact-graph traversal the Changes screen uses). This view answers how much, how severe, over time, not the authoritative score of any single change."
            ar="تستخدم مستويات الأولوية هنا عامل اتساع تنظيمي مبسّطًا (وليس اجتياز مخطط الأثر الفعلي لكل تغيير كما في شاشة التغييرات). تجيب هذه الشاشة عن الكمّ ومستوى الشدة عبر الزمن، لا عن الدرجة الرسمية لأي تغيير بعينه."
          />
        </span>
      </p>
    </main>
  );
}
