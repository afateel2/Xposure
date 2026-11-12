import {
  Box, Building2, FolderCheck, Layers, ListChecks, Package, ScrollText, ShieldCheck, User, Workflow,
  type LucideIcon,
} from "lucide-react";
import type { ErpInfo } from "@/lib/types-shared";
import type { BiText } from "@/lib/time";

/** Impacted node types (org graph) with a bilingual label, a plural group heading and an icon. */
export const NODE_TYPE_META: Record<string, { one: BiText; many: BiText; icon: LucideIcon }> = {
  policy: { one: { en: "Policy", ar: "سياسة" }, many: { en: "Policies", ar: "السياسات" }, icon: ScrollText },
  procedure: { one: { en: "Procedure", ar: "إجراء عمل" }, many: { en: "Procedures", ar: "إجراءات العمل" }, icon: ListChecks },
  process: { one: { en: "Process", ar: "عملية" }, many: { en: "Processes", ar: "العمليات" }, icon: Workflow },
  product: { one: { en: "Product", ar: "منتج" }, many: { en: "Products", ar: "المنتجات" }, icon: Package },
  evidence: { one: { en: "Evidence", ar: "دليل إثبات" }, many: { en: "Evidence", ar: "أدلة الإثبات" }, icon: FolderCheck },
  control_mapping: { one: { en: "Control mapping", ar: "ربط ضابط" }, many: { en: "Control mappings", ar: "ربط الضوابط" }, icon: ShieldCheck },
  site: { one: { en: "Site", ar: "موقع" }, many: { en: "Sites", ar: "المواقع" }, icon: Building2 },
  owner: { one: { en: "Owner", ar: "مالك" }, many: { en: "Owners", ar: "الملاك" }, icon: User },
};

export const NODE_TYPE_FALLBACK = { one: { en: "Other", ar: "أخرى" }, many: { en: "Other nodes", ar: "عناصر أخرى" }, icon: Box };
export const NODE_GROUP_ICON_FALLBACK: LucideIcon = Layers;

/** Order of groups on the Impact tab: what a person edits first, owners last. */
export const NODE_TYPE_ORDER = ["policy", "procedure", "process", "product", "evidence", "control_mapping", "site", "owner"];

export function nodeMeta(type: string) {
  return NODE_TYPE_META[type] ?? NODE_TYPE_FALLBACK;
}

/** Action types the executor turns into a real company file edit on approval. */
export const FILE_EDIT_ACTION_TYPES = new Set(["update_policy", "update_procedure", "technical_change"]);

export const ERP_STAGE_LABEL: Record<string, BiText> = {
  new: { en: "New", ar: "جديدة" },
  in_progress: { en: "In progress", ar: "قيد التنفيذ" },
  waiting: { en: "Waiting for confirmation", ar: "بانتظار التأكيد" },
  done: { en: "Done", ar: "منجزة" },
};

export function erpStageLabel(erp: Pick<ErpInfo, "stage" | "stage_key">): BiText {
  const key = erp.stage_key as string | undefined;
  if (key && ERP_STAGE_LABEL[key]) return ERP_STAGE_LABEL[key];
  const raw = erp.stage || "Unknown";
  return { en: raw, ar: raw };
}

/** Who did it, for the timeline. Audit actors look like "user:web", "agent:executor", "system:erp_sync". */
export function actorLabel(actor: string | null | undefined): BiText | null {
  if (!actor) return null;
  const map: Record<string, BiText> = {
    "user:web": { en: "You", ar: "أنت" },
    "agent:executor": { en: "Agent", ar: "الوكيل" },
    "agent:graph": { en: "Agent", ar: "الوكيل" },
    "system:erp_sync": { en: "ERP sync", ar: "مزامنة ERP" },
    "api:webhooks": { en: "Webhook", ar: "خطاف ويب" },
  };
  if (map[actor]) return map[actor];
  if (actor.startsWith("agent")) return { en: "Agent", ar: "الوكيل" };
  if (actor.startsWith("system")) return { en: "System", ar: "النظام" };
  return { en: actor, ar: actor };
}

/** Backend `effect_note` is English only; give the common reasons an Arabic rendering. */
export function effectNoteBi(note: string): BiText {
  const n = note.toLowerCase();
  const rules: [string, string][] = [
    ["does not execute", "لا ينفّذ الوكيل إجراءات من هذا النوع، لذا سُجّل الاعتماد كقرار فقط."],
    ["not linked to an impacted", "هذا الإجراء غير مرتبط بعنصر متأثر في المنشأة."],
    ["has no mapped", "العنصر المتأثر غير مرتبط بوثيقة أو ملف إعدادات في بيانات المنشأة، لذا سُجّل الاعتماد كقرار فقط."],
    ["does not exist", "الملف المرتبط غير موجود في مساحة عمل المنشأة."],
    ["is not allowed", "المسار المرتبط بالعنصر غير مسموح به."],
    ["found nothing to change", "لم يجد الوكيل ما يستوجب التغيير في الوثيقة."],
    ["could not produce a valid edit", "تعذّر على الوكيل إنتاج تعديل صالح."],
    ["unexpected error", "حدث خطأ غير متوقع أثناء التنفيذ."],
  ];
  const hit = rules.find(([needle]) => n.includes(needle));
  return { en: note, ar: hit ? hit[1] : note };
}
