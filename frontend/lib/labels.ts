// Bilingual display labels for the fixed vocabularies defined in
// backend/app/llm.py (CHANGE_TYPES), app/priority.py (bands) and
// app/policy.py (ACTION_TYPES, AUTOMATION_LEVELS). Restated here rather
// than fetched, since these are closed, stable vocabularies enforced in
// code on the backend (a change_type outside this list is a backend bug,
// not a UI concern) — same reasoning app/policy.py itself gives for
// restating app/llm.py's CHANGE_TYPES instead of importing them.

import type { ActionType, AutomationLevel, ChangeType, PriorityBand } from "./types";

export const CHANGE_TYPE_LABEL: Record<ChangeType, { en: string; ar: string }> = {
  new_obligation: { en: "New obligation", ar: "التزام جديد" },
  tightened: { en: "Tightened", ar: "تشديد" },
  relaxed: { en: "Relaxed", ar: "تخفيف" },
  clarification: { en: "Clarification", ar: "توضيح" },
  editorial: { en: "Editorial", ar: "تحرير" },
  renumbered: { en: "Renumbered", ar: "إعادة ترقيم" },
  withdrawn: { en: "Withdrawn", ar: "مُلغى" },
};

export const PRIORITY_BAND_LABEL: Record<PriorityBand, { en: string; ar: string }> = {
  critical: { en: "Critical", ar: "حرج" },
  high: { en: "High", ar: "عالي" },
  medium: { en: "Medium", ar: "متوسط" },
  low: { en: "Low", ar: "منخفض" },
};

export const ACTION_TYPE_LABEL: Record<ActionType, { en: string; ar: string }> = {
  update_policy: { en: "Update policy", ar: "تحديث سياسة" },
  update_procedure: { en: "Update procedure", ar: "تحديث إجراء" },
  technical_change: { en: "Technical change", ar: "تغيير تقني" },
  collect_evidence: { en: "Collect evidence", ar: "جمع أدلة" },
  reassess_control: { en: "Reassess control", ar: "إعادة تقييم الضابط" },
  notify_owner: { en: "Notify owner", ar: "إشعار المالك" },
  request_license_review: { en: "Request license review", ar: "طلب مراجعة ترخيص" },
};

export const AUTOMATION_LEVEL_LABEL: Record<AutomationLevel, { en: string; ar: string }> = {
  notify_only: { en: "Notify only", ar: "إشعار فقط" },
  draft_then_approve: { en: "Draft, then approve", ar: "مسودة ثم اعتماد" },
  auto_execute: { en: "Auto-execute", ar: "تنفيذ تلقائي" },
};

/** Why policy.explain_automation() capped or floored a level away from what the policy YAML requested. */
export const AUTOMATION_GATE_LABEL: Record<string, { en: string; ar: string }> = {
  tracked_decision_change_type: { en: "this kind of change always needs a tracked decision", ar: "هذا النوع من التغيير يتطلب دائماً قراراً موثقاً" },
  change_type_not_auto_executable: { en: "this kind of change is never auto-executed", ar: "هذا النوع من التغيير لا يُنفَّذ تلقائياً أبداً" },
  action_type_not_auto_executable: { en: "this action type is never auto-executed", ar: "هذا النوع من الإجراءات لا يُنفَّذ تلقائياً أبداً" },
  confidence_below_threshold: { en: "the model's confidence is below the auto-execute threshold", ar: "ثقة النموذج أقل من الحد المطلوب للتنفيذ التلقائي" },
};

export const ACTION_STATUS_LABEL: Record<string, { en: string; ar: string }> = {
  pending: { en: "Pending", ar: "قيد الانتظار" },
  approved: { en: "Approved", ar: "معتمد" },
  dismissed: { en: "Dismissed", ar: "مُتجاهَل" },
  awaiting_confirmation: { en: "Awaiting confirmation", ar: "بانتظار تأكيد الإنجاز" },
  done: { en: "Done (auto)", ar: "منجز (تلقائي)" },
};

export const MATCH_KIND_LABEL: Record<string, { en: string; ar: string }> = {
  exact_id: { en: "exact clause ID", ar: "تطابق تام في معرّف البند" },
  renumbered_candidate: { en: "matched by similarity", ar: "مطابقة بالتشابه" },
  new: { en: "new clause", ar: "بند جديد" },
  withdrawn: { en: "no counterpart", ar: "بلا مقابل" },
};

export const SCOPE_MATCH_LABEL: Record<string, { en: string; ar: string }> = {
  exact: { en: "exact control match", ar: "مطابقة تامة للضابط" },
  ancestor: { en: "broader scope than mapped", ar: "نطاق أوسع من المُعيّن" },
  descendant: { en: "narrower scope than mapped", ar: "نطاق أضيق من المُعيّن" },
};

/**
 * Arabic numeral-noun agreement for "N nodes affected": singular (1),
 * dual (2), plural noun (3-10), and back to singular noun for 11+ — the
 * standard Arabic cardinal-number rule, not just a number swapped into a
 * fixed phrase (which is only ever grammatically correct for 3-10).
 */
export function affectedNodesAr(count: number): string {
  if (count === 1) return "عقدة واحدة متأثرة";
  if (count === 2) return "عقدتان متأثرتان";
  if (count >= 3 && count <= 10) return `${count} عُقد متأثرة`;
  return `${count} عقدة متأثرة`;
}

/** Same cardinal-number agreement rule as affectedNodesAr, for "N days left". */
export function daysLeftAr(days: number): string {
  if (days === 0) return "اليوم";
  if (days === 1) return "يوم واحد متبقٍ";
  if (days === 2) return "يومان متبقيان";
  if (days >= 3 && days <= 10) return `${days} أيام متبقية`;
  return `${days} يومًا متبقيًا`;
}
