"use client";

import Link from "next/link";
import { Bi } from "@/components/Bi";
import { BrandMotif } from "@/components/ui";
import type { PriorityMatrix as Matrix } from "@/lib/types-visibility";

const BANDS = [
  { key: "critical", en: "Critical", ar: "حرج", tone: "danger" },
  { key: "quick", en: "Quick action", ar: "إجراء سريع", tone: "info" },
  { key: "strategic", en: "Strategic", ar: "استراتيجي", tone: "warning" },
  { key: "followup", en: "Follow-up", ar: "متابعة", tone: "muted" },
] as const;

/**
 * Four bands as one proportional bar plus a labelled count per band. Same
 * fixed colours as the priority pills; every segment is also named and
 * counted in the legend so colour is never the only signal.
 */
export function PriorityMatrix({ matrix }: { matrix: Matrix | null }) {
  if (!matrix) return <BrandMotif variant="spinner" compact title={<Bi en="Loading" ar="جارٍ التحميل" />} />;
  if (matrix.total === 0) {
    return (
      <BrandMotif
        compact
        title={<Bi en="Nothing to prioritise" ar="لا يوجد ما يستدعي ترتيب الأولويات" />}
        hint={<Bi en="Open review items appear here once the agent finds changes." ar="تظهر عناصر المراجعة المفتوحة هنا عندما يرصد الوكيل تغييرات." />}
      />
    );
  }
  const summary = BANDS.map((b) => `${b.en} ${matrix[b.key]}`).join(", ");
  return (
    <div className="dash-matrix">
      <div className="dash-bar" role="img" aria-label={`${summary}. Total ${matrix.total}.`}>
        {BANDS.map((b) => (matrix[b.key] > 0 ? <span key={b.key} className={`dash-bar-seg tone-${b.tone}`} style={{ flexGrow: matrix[b.key] }} /> : null))}
      </div>
      <ul className="dash-bands">
        {BANDS.map((b) => (
          <li key={b.key}>
            <Link href="/changes" className="dash-band">
              <span className={`dash-band-dot tone-${b.tone}`} aria-hidden="true" />
              <span className="dash-band-num tabular">{matrix[b.key]}</span>
              <span className="dash-band-label"><Bi en={b.en} ar={b.ar} /></span>
            </Link>
          </li>
        ))}
      </ul>
      <p className="dash-note">
        <Bi
          en="Changes still waiting for a decision, placed in four bands by priority."
          ar="التغييرات التي ما زالت بانتظار قرار، موزعة على أربعة مستويات بحسب الأولوية."
        />
      </p>
    </div>
  );
}
