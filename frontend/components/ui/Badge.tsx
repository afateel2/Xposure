import type { ReactNode } from "react";
import { Bi } from "../Bi";

export type BadgeVariant = "new" | "pending" | "approved" | "rejected" | "critical" | "info" | "warning" | "success" | "danger" | "neutral";

/**
 * Status badge. Fixed meanings everywhere: info/new = new, warning/pending =
 * pending, success/approved = approved or done, danger/rejected/critical =
 * rejected or critical. `neutral` is for dismissed or informational labels.
 */
export function Badge({ variant = "neutral", children, className }: { variant?: BadgeVariant; children: ReactNode; className?: string }) {
  return <span className={`xp-badge xp-badge-${variant}${className ? ` ${className}` : ""}`}>{children}</span>;
}

export type Priority = "critical" | "strategic" | "quick" | "followup";
export type PriorityInput = Priority | "high" | "medium" | "low";

/** Default mapping from the backend priority bands to the design system pills. */
export function bandToPriority(band: PriorityInput): Priority {
  switch (band) {
    case "high": return "strategic";
    case "medium": return "quick";
    case "low": return "followup";
    default: return band;
  }
}

const PRIORITY_LABEL: Record<Priority, { en: string; ar: string }> = {
  critical: { en: "Critical", ar: "حرج" },
  strategic: { en: "Strategic", ar: "استراتيجي" },
  quick: { en: "Quick action", ar: "إجراء سريع" },
  followup: { en: "Follow-up", ar: "متابعة" },
};

/**
 * Priority pill. Accepts a design system priority OR a backend band
 * (critical|high|medium|low, mapped through bandToPriority). Children are
 * optional: by default a bilingual label is rendered.
 */
export function PriorityPill({ priority, band, children, className }: { priority?: Priority; band?: PriorityInput; children?: ReactNode; className?: string }) {
  const p: Priority = priority ?? (band ? bandToPriority(band) : "followup");
  return (
    <span className={`xp-pill xp-pill-${p}${className ? ` ${className}` : ""}`}>
      {children ?? <Bi en={PRIORITY_LABEL[p].en} ar={PRIORITY_LABEL[p].ar} />}
    </span>
  );
}

/** Backend action status to badge variant (approved/done = success, etc.). */
export function actionStatusVariant(status: string): BadgeVariant {
  switch (status) {
    case "pending": return "pending";
    case "approved":
    case "done": return "approved";
    case "awaiting_confirmation": return "new";
    case "rejected": return "rejected";
    default: return "neutral";
  }
}
