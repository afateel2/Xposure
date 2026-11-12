import type {
  AgentStatusOut,
  BulkActionRequest,
  BulkActionResult,
  ChangeDetailOut,
  ChangeSummaryOut,
  CommandPreviewOut,
  DelegateActionRequest,
  DigestStatusOut,
  EvalSummaryOut,
  HealthResponse,
  PolicyOut,
  ReceivedWebhookOut,
  SentNotificationOut,
  SourceVersionOut,
  SuggestionOut,
  TrendPointOut,
  UndoResult,
} from "./types";

// Every call goes through Next's own /api/* routes, which proxy to the
// FastAPI backend server-side (BACKEND_URL) — the browser never talks to
// the backend directly. Pattern carried over from ComplyX's lib/api.ts.

export async function getHealth(): Promise<HealthResponse> {
  const res = await fetch("/api/health", { cache: "no-store" });
  return res.json();
}

export interface ListChangesParams {
  materialOnly?: boolean;
  band?: string;
}

export async function getChanges(params: ListChangesParams = {}): Promise<ChangeSummaryOut[]> {
  const search = new URLSearchParams();
  if (params.materialOnly !== undefined) search.set("material_only", String(params.materialOnly));
  if (params.band) search.set("band", params.band);
  const qs = search.toString();
  const res = await fetch(`/api/changes${qs ? `?${qs}` : ""}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`GET /api/changes failed: ${res.status}`);
  return res.json();
}

export async function getChange(id: number): Promise<ChangeDetailOut> {
  const res = await fetch(`/api/changes/${id}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`GET /api/changes/${id} failed: ${res.status}`);
  return res.json();
}

export interface ApproveActionResult {
  id: number;
  status: string;
  /** The agent's file edit, when approving an action mapped to a company file. */
  effect?: import("./types-shared").ActionEffect | null;
  /** Plain-language reason when the approval had no file effect. */
  effect_note?: string | null;
}

export async function approveAction(id: number): Promise<ApproveActionResult> {
  const res = await fetch(`/api/actions/${id}/approve`, { method: "POST" });
  if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? `Approve failed: ${res.status}`);
  return res.json();
}

/** A dismissal always carries a written reason; the backend refuses it without one. */
export async function dismissAction(id: number, reason: string): Promise<{ id: number; status: string; reason?: string }> {
  const res = await fetch(`/api/actions/${id}/dismiss`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? `Dismiss failed: ${res.status}`);
  return res.json();
}

export async function getSources(): Promise<SourceVersionOut[]> {
  const res = await fetch("/api/sources", { cache: "no-store" });
  if (!res.ok) throw new Error(`GET /api/sources failed: ${res.status}`);
  return res.json();
}

export async function getPolicy(): Promise<PolicyOut> {
  const res = await fetch("/api/settings/policy", { cache: "no-store" });
  if (!res.ok) throw new Error(`GET /api/settings/policy failed: ${res.status}`);
  return res.json();
}

export async function getReceivedWebhooks(): Promise<ReceivedWebhookOut[]> {
  const res = await fetch("/api/webhooks/received", { cache: "no-store" });
  if (!res.ok) throw new Error(`GET /api/webhooks/received failed: ${res.status}`);
  return res.json();
}

export async function getAgentStatus(): Promise<AgentStatusOut> {
  const res = await fetch("/api/agent/status", { cache: "no-store" });
  if (!res.ok) throw new Error(`GET /api/agent/status failed: ${res.status}`);
  return res.json();
}

export interface DelegateActionResult {
  id: number;
  status: string;
  assignee_name: string | null;
  assignee_contact: string | null;
  erp?: import("./types-shared").ErpInfo | null;
}

export async function delegateAction(id: number, body: DelegateActionRequest): Promise<DelegateActionResult> {
  const res = await fetch(`/api/actions/${id}/delegate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? `Delegate failed: ${res.status}`);
  return res.json();
}

export async function confirmAction(id: number): Promise<{ id: number; status: string }> {
  const res = await fetch(`/api/actions/${id}/confirm`, { method: "POST" });
  if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? `Confirm failed: ${res.status}`);
  return res.json();
}

export async function undoAction(id: number): Promise<UndoResult> {
  const res = await fetch(`/api/actions/${id}/undo`, { method: "POST" });
  if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? `Undo failed: ${res.status}`);
  return res.json();
}

export async function bulkAction(body: BulkActionRequest): Promise<BulkActionResult> {
  const res = await fetch("/api/actions/bulk", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? `Bulk action failed: ${res.status}`);
  return res.json();
}

export interface GetTrendsParams {
  regulator?: string;
  regulation?: string;
  materialOnly?: boolean;
}

export async function getTrends(params: GetTrendsParams = {}): Promise<TrendPointOut[]> {
  const search = new URLSearchParams();
  if (params.regulator) search.set("regulator", params.regulator);
  if (params.regulation) search.set("regulation", params.regulation);
  if (params.materialOnly !== undefined) search.set("material_only", String(params.materialOnly));
  const qs = search.toString();
  const res = await fetch(`/api/trends${qs ? `?${qs}` : ""}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`GET /api/trends failed: ${res.status}`);
  return res.json();
}

export async function getSuggestions(): Promise<SuggestionOut[]> {
  const res = await fetch("/api/agent/suggestions", { cache: "no-store" });
  if (!res.ok) throw new Error(`GET /api/agent/suggestions failed: ${res.status}`);
  return res.json();
}

export async function previewCommand(command: string): Promise<CommandPreviewOut> {
  const res = await fetch("/api/agent/command_preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command }),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? `Command preview failed: ${res.status}`);
  return res.json();
}

export async function getEvalSummary(): Promise<EvalSummaryOut | null> {
  const res = await fetch("/api/agent/eval-summary", { cache: "no-store" });
  if (!res.ok) throw new Error(`GET /api/agent/eval-summary failed: ${res.status}`);
  return res.json();
}

export async function getSentNotifications(): Promise<SentNotificationOut[]> {
  const res = await fetch("/api/notifications/sent", { cache: "no-store" });
  if (!res.ok) throw new Error(`GET /api/notifications/sent failed: ${res.status}`);
  return res.json();
}

export async function getDigestStatus(): Promise<DigestStatusOut> {
  const res = await fetch("/api/agent/digest-status", { cache: "no-store" });
  if (!res.ok) throw new Error(`GET /api/agent/digest-status failed: ${res.status}`);
  return res.json();
}
