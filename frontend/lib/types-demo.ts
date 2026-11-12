/**
 * Types for the live demo pipeline (backend/app/routes/demo.py,
 * backend/app/demo/). Mirrors GET /demo/run, GET /demo/status, GET /activity
 * and GET /agent/state.
 */

export type RunStatus = "idle" | "running" | "awaiting_review" | "completed" | "failed";
export type StageStatus = "pending" | "running" | "done" | "failed";
export type DemoPhase = "baseline" | "scanning" | "review_ready";

export type StageCounts = Record<string, number | string | boolean | null | Record<string, number>>;

export interface DemoStage {
  key: string;
  label_en: string;
  label_ar: string;
  status: StageStatus;
  detail_en: string | null;
  detail_ar: string | null;
  counts: StageCounts | null;
  started_at: string | null;
  ended_at: string | null;
}

export interface DemoRun {
  run_id: string | null;
  status: RunStatus;
  started_at: string | null;
  finished_at: string | null;
  stages: DemoStage[];
  note_en: string | null;
  note_ar: string | null;
  error?: { stage: string | null; reason: string | null; error_type: string | null } | null;
  summary?: Record<string, unknown> | null;
}

export interface DemoRegulationVersion {
  regulator: string;
  regulation: string;
  version_label: string;
  clause_count: number;
  file_sha256?: string | null;
  ingested_at?: string | null;
}

export interface DemoPortalDoc {
  path?: string;
  filename: string;
  version_label: string | null;
  size_bytes?: number;
  status: "new" | "known" | "conflict" | "unrecognized" | string;
}

export interface DemoStatus {
  phase: DemoPhase;
  demo_mode: boolean;
  regulation_versions: DemoRegulationVersion[];
  run_status?: RunStatus;
  run_id?: string | null;
  pending_actions?: number;
  total_actions?: number;
  needs_reset?: boolean;
  can_scan?: boolean;
  can_reset?: boolean;
  last_reset_at?: string | null;
  portal?: {
    simulated: boolean;
    note_en: string;
    note_ar: string;
    documents: DemoPortalDoc[];
    new_available: number;
  };
  stage_pacing_ms?: number;
  llm_cache?: { enabled: boolean; entries: number };
}

export interface ScanStarted {
  run_id: string;
  [key: string]: unknown;
}

export interface ActivityItem {
  id: number;
  ts: string;
  kind: string;
  severity: "info" | "success" | "warning" | "danger";
  icon: string;
  text_en: string;
  text_ar: string;
  detail_en: string | null;
  detail_ar: string | null;
  actor: string;
  event: string;
  count: number;
}

export interface ActivityFeed {
  items: ActivityItem[];
  next_before_id: number | null;
}

export interface AgentStateLite {
  state: "idle" | "scanning" | "awaiting_review" | "failed";
  awaiting_count?: number | null;
  awaiting_changes?: number | null;
  last_scan_at?: string | null;
  message_en?: string;
  message_ar?: string;
}

/**
 * Fallback stage list used only to keep the layout stable before the first
 * run (an idle run has every stage pending anyway). Matches
 * backend/app/demo/constants.py. Never used to invent progress.
 */
export const FALLBACK_STAGES: DemoStage[] = [
  ["portal", "Checking the regulator portal", "فحص بوابة الجهة التنظيمية"],
  ["fetch", "Fetching the new document", "جلب الوثيقة الجديدة"],
  ["ingest", "Reading and indexing the document", "قراءة الوثيقة وفهرستها"],
  ["align", "Matching clauses between versions", "مطابقة البنود بين الإصدارين"],
  ["classify", "Classifying each change", "تصنيف كل تغيير"],
  ["impact", "Tracing impact through the company", "تتبع الأثر على الشركة"],
  ["prioritize", "Prioritizing by risk", "ترتيب الأولويات حسب المخاطر"],
  ["policy", "Applying the automation policy", "تطبيق سياسة الأتمتة"],
  ["auto_execute", "Executing safe actions automatically", "تنفيذ الإجراءات الآمنة تلقائيًا"],
  ["review", "Ready for human review", "جاهز للمراجعة البشرية"],
].map(([key, en, ar]) => ({
  key, label_en: en, label_ar: ar, status: "pending" as const, detail_en: null, detail_ar: null, counts: null, started_at: null, ended_at: null,
}));
