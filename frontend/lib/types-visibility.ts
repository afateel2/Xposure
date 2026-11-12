/**
 * Response shapes of the visibility endpoints (mirrors
 * backend/app/visibility/schemas.py). Timestamps are ISO strings in UTC.
 */
import type { ActionEffect, ErpInfo } from "./types-shared";

export type Severity = "info" | "success" | "warning" | "danger";
export type ActivityKind =
  | "scan" | "ingest" | "diff" | "classify" | "impact" | "action" | "delegate" | "confirm" | "undo" | "export" | "system" | "effect";

export interface WindowInfo {
  since_reset: boolean;
  reset_at: string | null;
}

export interface MonitoringInfo {
  sources_total: number;
  sources_ok: number;
  sources_planned: number;
  last_scan_at: string | null;
  last_release_detected_at: string | null;
  mean_hours_publish_to_alert: number | null;
  mean_hours_sample_size: number;
  stale_after_hours: number;
  file_issues: { conflict: number; unrecognized: number };
  scope_note_en: string;
  scope_note_ar: string;
}

export interface ReviewQueue {
  total: number;
  critical: number;
  urgent: number;
  strategic: number;
  followup: number;
  awaiting_confirmation: number;
  pending_actions: number;
  basis_en: string;
  basis_ar: string;
}

export interface TaskCounts {
  open: number;
  due_within_5_days: number;
  overdue: number;
  definition_en: string;
  definition_ar: string;
}

export interface PriorityMatrix {
  critical: number;
  quick: number;
  strategic: number;
  followup: number;
  total: number;
  basis_en: string;
  basis_ar: string;
  all_material: Record<string, number>;
}

export interface Remediation {
  total_actions: number;
  resolved_actions: number;
  percent: number | null;
  by_status: Record<string, number>;
}

export type SourceStatus = "ok" | "attention" | "stale" | "planned";

export interface OverviewSource {
  code: string;
  regulator_code: string;
  regulation_code: string | null;
  name_en: string;
  name_ar: string;
  title_en: string | null;
  title_ar: string | null;
  latest_version: string | null;
  latest_version_ingested_at: string | null;
  last_checked_at: string | null;
  last_change_at: string | null;
  open_changes: number;
  changes_total: number;
  status: SourceStatus;
  status_reason: string;
  status_label_en: string;
  status_label_ar: string;
  planned: boolean;
  scope_en: string | null;
  scope_ar: string | null;
}

export interface Overview {
  generated_at: string;
  window: WindowInfo;
  monitoring: MonitoringInfo;
  review_queue: ReviewQueue;
  tasks: TaskCounts;
  priority_matrix: PriorityMatrix;
  remediation: Remediation;
  sources: OverviewSource[];
}

export interface NewCount {
  since: string;
  total: number;
  by_band: Record<string, number>;
  by_matrix: Record<string, number>;
  latest_created_at: string | null;
}

export interface ActivityItem {
  id: number;
  first_id: number;
  ts: string;
  ts_start: string;
  kind: ActivityKind;
  severity: Severity;
  icon: string;
  text_en: string;
  text_ar: string;
  detail_en: string | null;
  detail_ar: string | null;
  ref_type: string | null;
  ref_id: number | null;
  change_id: number | null;
  action_id: number | null;
  actor: string;
  event: string;
  count: number;
}

export interface ActivityPage {
  items: ActivityItem[];
  next_before_id: number | null;
  window: WindowInfo;
}

export interface AuditRow {
  id: number;
  ts: string;
  actor: string;
  event: string;
  ref_type: string;
  ref_id: number | null;
  kind: ActivityKind;
  severity: Severity;
  icon: string;
  summary_en: string;
  summary_ar: string;
  payload: Record<string, unknown> | null;
}

export interface AuditPage {
  items: AuditRow[];
  total: number;
  limit: number;
  offset: number;
}

export interface AuditEventInfo {
  event: string;
  count: number;
  kind: ActivityKind;
  label_en: string;
  label_ar: string;
}

export interface AuditActorInfo {
  actor: string;
  count: number;
}

export type AgentStateName = "idle" | "scanning" | "awaiting_review" | "failed";

export interface AgentState {
  state: AgentStateName;
  since: string | null;
  awaiting_count: number;
  awaiting_changes: number;
  awaiting_confirmation_count: number;
  last_scan_at: string | null;
  last_run_status: "completed" | "failed" | "awaiting_review" | null;
  last_run_summary: Record<string, unknown> | null;
  last_run_at: string | null;
  run_id: string | null;
  stage: { key: string; label_en: string; label_ar: string } | null;
  stalled: boolean;
  message_en: string;
  message_ar: string;
}

export type TaskStatus = "pending" | "awaiting_confirmation" | "approved" | "done" | "dismissed";
export type PriorityKey = "critical" | "quick" | "strategic" | "followup";

/** ERP block of /tasks (a trimmed ErpInfo; fields can be null before the first sync). */
export type TaskErp = Partial<Omit<ErpInfo, "system">> & { system?: string | null };

export interface TaskItem {
  id: number;
  action_type: string;
  action_type_label_en: string;
  action_type_label_ar: string;
  level: string;
  status: TaskStatus | string;
  status_label_en: string;
  status_label_ar: string;
  change_id: number;
  change_title_en: string;
  change_title_ar: string;
  clause_ref: string | null;
  regulator_code: string | null;
  regulation_code: string | null;
  priority_band: "critical" | "high" | "medium" | "low" | null;
  priority_key: PriorityKey | null;
  priority_score: number | null;
  due_date: string | null;
  is_overdue: boolean;
  days_left: number | null;
  assignee_name: string | null;
  assignee_contact: string | null;
  owner_node_name: string | null;
  impact_node_name: string | null;
  erp: TaskErp | null;
  effect: (Partial<ActionEffect> & { has_diff?: boolean }) | null;
  delegated_at: string | null;
  confirmed_at: string | null;
  created_at: string;
  last_event_at: string | null;
}

export interface TasksSummary {
  total: number;
  by_status: Record<string, number>;
  open: number;
  due_within_5_days: number;
  overdue: number;
  pending_review: number;
  pending_review_overdue: number;
  assigned: number;
}

export interface TasksPage {
  items: TaskItem[];
  total: number;
  limit: number;
  offset: number;
  summary: TasksSummary;
}

export interface ErpSyncResult {
  [key: string]: unknown;
}
