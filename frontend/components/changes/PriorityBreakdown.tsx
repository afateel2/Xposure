import { Bi } from "@/components/Bi";
import { Card, PriorityPill } from "@/components/ui";
import type { ChangeDetailOut } from "@/lib/types";

const FACTORS: { key: "severity_weight" | "impact_factor" | "deadline_factor" | "regulator_weight"; en: string; ar: string }[] = [
  { key: "severity_weight", en: "Change severity", ar: "شدة التغيير" },
  { key: "impact_factor", en: "Organizational reach", ar: "اتساع الأثر التنظيمي" },
  { key: "deadline_factor", en: "Deadline proximity", ar: "قرب الموعد النهائي" },
  { key: "regulator_weight", en: "Regulator weight", ar: "وزن الجهة التنظيمية" },
];

const fmt = (n: number) => (Number.isInteger(n) ? String(n) : String(Math.round(n * 100) / 100));

/** The deterministic priority arithmetic, shown as a product so nobody has to trust a number. */
export function PriorityBreakdown({ detail }: { detail: ChangeDetailOut }) {
  const b = detail.priority_breakdown;
  return (
    <Card
      className="chg-prio"
      title={<Bi en="Why this priority" ar="سبب هذه الأولوية" />}
      actions={<PriorityPill band={detail.priority_band} />}
    >
      <div className="chg-eq" role="math" aria-label="priority equation">
        {FACTORS.map((f, i) => (
          <span key={f.key} className="chg-eq-part">
            {i > 0 && <span className="chg-eq-op" aria-hidden="true">{"×"}</span>}
            <span className="chg-eq-term">
              <span className="chg-eq-val tabular">{fmt(b[f.key])}</span>
              <span className="chg-eq-lbl"><Bi en={f.en} ar={f.ar} /></span>
            </span>
          </span>
        ))}
        <span className="chg-eq-part">
          <span className="chg-eq-op" aria-hidden="true">=</span>
          <span className="chg-eq-term is-result">
            <span className="chg-eq-val tabular">{fmt(b.raw)}</span>
            <span className="chg-eq-lbl"><Bi en="Raw score" ar="الدرجة الخام" /></span>
          </span>
        </span>
      </div>
      <p className="chg-prio-note">
        <Bi
          en={<>Score <b className="tabular">{detail.priority_score}</b> = raw score divided by the reference score <span className="tabular">{fmt(b.reference_raw)}</span>, scaled to 100. Computed by code (<bdi className="mono">app/priority.py</bdi>), recomputed live.</>}
          ar={<>الدرجة <b className="tabular">{detail.priority_score}</b> = الدرجة الخام مقسومة على الدرجة المرجعية <span className="tabular">{fmt(b.reference_raw)}</span> ومقيسة على 100. يحسبها الكود (<bdi className="mono">app/priority.py</bdi>) وتُعاد مباشرةً.</>}
        />
        {b.gate && (
          <span className="chg-prio-gate">
            {" "}
            <Bi
              en={`Capped at ${b.gate.cap}: ${b.gate.kind.replace(/_/g, " ")}.`}
              ar={`مُقيَّدة بحد أقصى ${b.gate.cap}: ${b.gate.kind === "not_material" ? "غير جوهري" : b.gate.kind.replace(/_/g, " ")}.`}
            />
          </span>
        )}
      </p>
    </Card>
  );
}
