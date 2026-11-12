import { Bi } from "@/components/Bi";
import { Badge, type BadgeVariant } from "@/components/ui";
import type { BiText } from "@/lib/time";
import type { FileKind, FileOrigin, NodeStatus } from "@/lib/types-company";

export const KIND_LABEL: Record<FileKind, { en: string; ar: string; plural: BiText }> = {
  policy: { en: "Policy", ar: "سياسة", plural: { en: "Policies", ar: "السياسات" } },
  procedure: { en: "Procedure", ar: "إجراء", plural: { en: "Procedures", ar: "الإجراءات" } },
  evidence: { en: "Evidence", ar: "دليل إثبات", plural: { en: "Evidence", ar: "أدلة الإثبات" } },
  system: { en: "System settings", ar: "إعدادات نظام", plural: { en: "System settings", ar: "إعدادات الأنظمة" } },
  other: { en: "Other", ar: "أخرى", plural: { en: "Other", ar: "أخرى" } },
};

export const KIND_ORDER: FileKind[] = ["policy", "procedure", "evidence", "system", "other"];

export const ORIGIN_LABEL: Record<FileOrigin, { en: string; ar: string }> = {
  baseline: { en: "Baseline copy", ar: "النسخة المرجعية" },
  agent: { en: "Edited by the agent", ar: "عدّلها الوكيل" },
  revert: { en: "Restored by a person", ar: "استعادها مستخدم" },
};

export const ORIGIN_WHO: Record<FileOrigin, { en: string; ar: string }> = {
  baseline: { en: "System", ar: "النظام" },
  agent: { en: "Agent", ar: "الوكيل" },
  revert: { en: "You (restore)", ar: "أنت (استعادة)" },
};

const STATUS: Record<NodeStatus, { variant: BadgeVariant; en: string; ar: string }> = {
  up_to_date: { variant: "neutral", en: "Up to date", ar: "محدّث" },
  action_required: { variant: "pending", en: "Action needed", ar: "يتطلب إجراءً" },
  assigned: { variant: "new", en: "Awaiting confirmation", ar: "بانتظار التأكيد" },
  updated_by_agent: { variant: "approved", en: "Updated by agent", ar: "عُدِّل بواسطة الوكيل" },
};

export function NodeStatusBadge({ status }: { status: NodeStatus }) {
  const s = STATUS[status] ?? STATUS.up_to_date;
  return <Badge variant={s.variant}><Bi en={s.en} ar={s.ar} /></Badge>;
}

export const STATUS_ORDER: NodeStatus[] = ["action_required", "assigned", "updated_by_agent", "up_to_date"];
export const STATUS_TEXT = STATUS;

export function AgentChip() {
  return (
    <span className="fac-agent-chip">
      <Bi en="Modified by agent" ar="عدّلها الوكيل" />
    </span>
  );
}

export function fmtSize(bytes: number): string {
  return bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KB`;
}
