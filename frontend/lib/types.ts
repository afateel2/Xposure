// Mirrors backend/app/routes/schemas.py exactly, same discipline as
// ComplyX's lib/types.ts — every Pydantic API contract model gets a
// matching type here, kept in sync by hand.

import type { ActionEffect, ErpInfo } from "./types-shared";

export interface HealthResponse {
  status: "ok" | "degraded" | "offline";
  ready: boolean;
  db?: { reachable: boolean };
  qdrant?: { reachable: boolean; collection_exists?: boolean; error?: string };
  llm?: {
    reachable: boolean;
    base_url?: string;
    configured_model?: string;
    model_available?: boolean;
    error?: string;
  };
}

export type PriorityBand = "critical" | "high" | "medium" | "low";
export type ChangeType =
  | "new_obligation" | "tightened" | "relaxed" | "clarification"
  | "editorial" | "renumbered" | "withdrawn";
export type ActionType =
  | "update_policy" | "update_procedure" | "technical_change" | "collect_evidence"
  | "reassess_control" | "notify_owner" | "request_license_review";
export type AutomationLevel = "notify_only" | "draft_then_approve" | "auto_execute";
export type ActionStatus = "pending" | "approved" | "dismissed" | "awaiting_confirmation" | "done";

export interface RegulatorOut {
  code: string;
  name_en: string;
  name_ar: string;
}

export interface RegulationOut {
  code: string;
  title_en: string;
  title_ar: string;
}

export interface ActionOut {
  id: number;
  type: ActionType;
  level: AutomationLevel;
  status: ActionStatus;
  due_date: string | null;
  owner_node_name: string | null;
  created_at: string;
  assignee_name: string | null;
  assignee_contact: string | null;
  delegated_at: string | null;
  confirmed_at: string | null;
  can_undo: boolean;
  is_redo: boolean;
  /** The agent's file edit for this action (null when none or undone). */
  effect?: ActionEffect | null;
  /** The ERP (Odoo) task when the action was delegated through Odoo. */
  erp?: ErpInfo | null;
  /** The automation level the policy requested before any gate moved it. */
  automation_requested?: AutomationLevel | null;
  /** Which gates capped or floored the level away from automation_requested (empty = granted as written). */
  automation_gates?: string[] | null;
  /** The written reason the reviewer gave when dismissing this action (only while it is dismissed). */
  dismiss_reason?: string | null;
}

export interface ImpactOut {
  id: number;
  node_id: number;
  node_type: string;
  node_name: string;
  scope_match: string;
  depth: number;
  path_summary: string;
  note_en: string;
  note_ar: string;
  recommended_actions: ActionType[];
  actions: ActionOut[];
}

export interface PriorityBreakdownOut {
  severity_weight: number;
  impact_factor: number;
  deadline_factor: number;
  regulator_weight: number;
  raw: number;
  reference_raw: number;
  ungated_score: number;
  gate: { kind: string; cap: number } | null;
}

export interface ChangeSummaryOut {
  id: number;
  regulator: RegulatorOut;
  regulation: RegulationOut;
  old_clause_id: string | null;
  new_clause_id: string | null;
  clause_ref: string | null;
  match_kind: "exact_id" | "renumbered_candidate" | "new" | "withdrawn";
  change_type: ChangeType | null;
  material: boolean | null;
  confidence: number | null;
  summary_en: string;
  summary_ar: string;
  effective_date: string | null;
  grace_days: number | null;
  due_date: string | null;
  priority_score: number;
  priority_band: PriorityBand;
  priority_breakdown: PriorityBreakdownOut;
  days_to_effective: number | null;
  is_overdue: boolean;
  impacted_node_count: number;
  action_status_counts: Partial<Record<ActionStatus, number>>;
  assigned_to: string[];
  created_at: string;
}

export interface DiffOp {
  op: "replace" | "delete" | "insert";
  old: string[];
  new: string[];
}

/** Result of the citation check (backend/app/citation.py) for one side of a change. */
export type CitationStatus = "verified" | "other_page" | "not_found" | "file_changed" | "unavailable";

export interface CitationCheckOut {
  status: CitationStatus;
  /** Page (1-based) where the text was found. */
  page: number | null;
  /** Page the change cites. */
  cited_page: number | null;
  file_hash_ok: boolean | null;
  reason: string | null;
}

export interface CitationOut {
  old: CitationCheckOut | null;
  new: CitationCheckOut | null;
}

export interface ChangeDetailOut extends ChangeSummaryOut {
  match_score: number | null;
  old_text_en: string | null;
  old_text_ar: string | null;
  new_text_en: string | null;
  new_text_ar: string | null;
  old_page: number | null;
  new_page: number | null;
  old_version_label: string | null;
  new_version_label: string | null;
  from_file_sha256: string;
  to_file_sha256: string;
  diff_ops: DiffOp[];
  impacts: ImpactOut[];
  /** Is the clause text really in the stored source file? Absent on older backends. */
  citation?: CitationOut | null;
}

export interface SourceVersionOut {
  regulator: RegulatorOut;
  regulation: RegulationOut;
  version_label: string;
  published_at: string | null;
  effective_at: string | null;
  source_url: string;
  file_sha256: string;
  ingested_at: string;
  clause_count: number;
  has_live_check: boolean;
}

export interface PolicyGateOut {
  id: string;
  description_en: string;
}

export interface ReceivedWebhookOut {
  id: number;
  ts: string;
  event: string;
  payload: Record<string, unknown>;
}

export interface PolicyOut {
  default_level: AutomationLevel;
  action_types: ActionType[];
  automation_levels: AutomationLevel[];
  action_levels: Record<string, AutomationLevel>;
  auto_executable_change_types: ChangeType[];
  tracked_decision_change_types: ChangeType[];
  auto_executable_action_types: ActionType[];
  min_auto_execute_confidence: number;
  gates: PolicyGateOut[];
}

export interface AgentStatusOut {
  last_checked_at: string | null;
  last_run_at: string | null;
  last_run_status: "delivered" | "failed" | null;
  last_run_summary: Record<string, unknown> | null;
  last_baseline_ingested_at: string | null;
  last_baseline_ingested_label: string | null;
}

export interface DelegateActionRequest {
  /** Required unless channel is "odoo" (then employee_id identifies the person). */
  assignee_name?: string | null;
  assignee_contact?: string | null;
  message?: string | null;
  channel?: "odoo" | null;
  employee_id?: number | null;
  note?: string | null;
}

export interface BulkActionRequest {
  action_ids: number[];
  decision: "approve" | "dismiss";
  /** Required by the backend when decision is "dismiss". */
  reason?: string;
}

export interface BulkActionResult {
  updated: number[];
  skipped: { id: number; reason: string }[];
}

export interface UndoResult {
  id: number;
  status: ActionStatus;
  side_effects_not_reversed: string[];
  /** Set when undo restored the agent's file edit. */
  effect_reverted?: (ActionEffect & { reverted_at?: string; version_restored?: number }) | null;
  /** Set when a redo applied the (cached) edit again. */
  effect_reapplied?: ActionEffect | null;
}

export interface TrendPointOut {
  period: string;
  regulator_code: string;
  regulation_code: string;
  change_type: ChangeType;
  band: PriorityBand;
  count: number;
}

export interface SuggestionOut {
  id: string;
  text_en: string;
  text_ar: string;
}

export interface CommandPreviewOut {
  matched_change_ids: number[];
  matched_action_ids: number[];
  proposed_decision: "approve" | "dismiss" | "summarize" | null;
  confidence: number;
  explanation_en: string;
  explanation_ar: string;
}

export interface EvalSummaryOut {
  model: string;
  base_url: string | null;
  sample_size: number;
  structured_output_validity_rate: number | null;
  avg_latency_s: number | null;
  labeled_sample_size: number;
  accuracy_on_labeled: number | null;
}

export interface SentNotificationOut {
  id: number;
  ts: string;
  action_id: number;
  assignee_name: string | null;
  notification: { sent: boolean; channel?: string; target?: string; reason?: string } | null;
}

export interface DigestStatusOut {
  last_digest_at: string | null;
  last_digest_status: "sent" | "skipped" | null;
  last_digest_summary: Record<string, unknown> | null;
}
