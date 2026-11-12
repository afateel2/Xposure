import type { DelegateActionResult } from "./api";
import type { ErpEmployee, ErpStatus } from "./types-shared";

/**
 * ERP (Odoo) helpers. Everything goes through the generic /api proxy, so a
 * missing backend route surfaces as a 404 ApiError that the UI turns into an
 * honest "not available" state instead of fake data.
 */

/** Backend error with a bilingual message (ERP errors arrive as "English | Arabic"). */
export class ApiError extends Error {
  status: number;
  en: string;
  ar: string;
  constructor(status: number, en: string, ar?: string) {
    super(en);
    this.name = "ApiError";
    this.status = status;
    this.en = en;
    this.ar = ar ?? en;
  }
}

/** Turns a FastAPI `detail` (string, "English | Arabic", or validation list) into en/ar text. */
export function splitDetail(detail: unknown, fallback: string): { en: string; ar: string } {
  if (typeof detail === "string" && detail.trim() !== "") {
    const idx = detail.indexOf(" | ");
    if (idx > 0) return { en: detail.slice(0, idx).trim(), ar: detail.slice(idx + 3).trim() };
    return { en: detail, ar: detail };
  }
  if (Array.isArray(detail)) {
    const msg = detail
      .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : ""))
      .filter(Boolean)
      .join("; ");
    if (msg) return { en: msg, ar: msg };
  }
  return { en: fallback, ar: fallback };
}

/** Normalizes any thrown value into en/ar text. */
export function errorText(err: unknown): { en: string; ar: string } {
  if (err instanceof ApiError) return { en: err.en, ar: err.ar };
  const raw = err instanceof Error ? err.message : String(err);
  return splitDetail(raw, raw);
}

async function failure(res: Response, fallback: string): Promise<ApiError> {
  const body = await res.json().catch(() => null);
  const { en, ar } = splitDetail(body?.detail, `${fallback}: ${res.status}`);
  return new ApiError(res.status, en, ar);
}

/** What GET /erp/status returns beyond the shared type (honest connectivity flags). */
export type ErpStatusFull = ErpStatus & { authenticated?: boolean; project_found?: boolean };

/** True when the status says a task can really be created right now. */
export function erpIsConnected(status: ErpStatusFull | null): boolean {
  return !!status && status.configured && status.reachable && status.authenticated !== false && status.project_found !== false;
}

/** GET /erp/status. Throws ApiError (404 when this server has no ERP integration). */
export async function getErpStatus(): Promise<ErpStatusFull> {
  const res = await fetch("/api/erp/status", { cache: "no-store" });
  if (!res.ok) throw await failure(res, "GET /api/erp/status failed");
  return res.json();
}

/** GET /erp/employees, for the assignee picker. */
export async function getErpEmployees(): Promise<ErpEmployee[]> {
  const res = await fetch("/api/erp/employees", { cache: "no-store" });
  if (!res.ok) throw await failure(res, "GET /api/erp/employees failed");
  return res.json();
}

/** POST /erp/sync: re-reads every Odoo task and applies Done to the linked actions. */
export async function syncErp(): Promise<Record<string, unknown>> {
  const res = await fetch("/api/erp/sync", { method: "POST" });
  if (!res.ok) throw await failure(res, "ERP sync failed");
  return res.json();
}

/** Delegates a pending action through Odoo: creates a real task (fails loudly if Odoo refuses). */
export async function delegateToOdoo(actionId: number, employeeId: number, note?: string): Promise<DelegateActionResult> {
  const res = await fetch(`/api/actions/${actionId}/delegate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ channel: "odoo", employee_id: employeeId, note: note?.trim() ? note.trim() : null }),
  });
  if (!res.ok) throw await failure(res, "Delegate failed");
  return res.json();
}

/** Email of an owner node from the Facility profile (best effort: null when unavailable). */
export async function getOwnerEmail(nodeName: string): Promise<string | null> {
  try {
    const res = await fetch("/api/company/nodes", { cache: "no-store" });
    if (!res.ok) return null;
    const body = await res.json();
    const nodes: { type?: string; name?: string; attrs?: { email?: string } }[] = Array.isArray(body) ? body : body?.nodes ?? [];
    const hit = nodes.find((n) => n.type === "owner" && n.name === nodeName);
    return hit?.attrs?.email ?? null;
  } catch {
    return null;
  }
}

export type NodeOwner = { id: number; name: string; email: string | null; role: string | null };

/**
 * The owner the org graph already resolves for a node (one hop via an `owned_by`
 * edge, computed server-side in app/company/nodes.py's build_nodes()). When the
 * impacted node IS an owner node itself (the action already names a person
 * directly, e.g. "IT Security Lead"), that node is its own owner. Best effort:
 * null when neither applies (e.g. a product or evidence node with no direct
 * owner edge) or the lookup fails, never a guess.
 */
export async function getNodeOwner(nodeId: number): Promise<NodeOwner | null> {
  try {
    const res = await fetch("/api/company/nodes", { cache: "no-store" });
    if (!res.ok) return null;
    const body = await res.json();
    const nodes: { id?: number; type?: string; name?: string; attrs?: { email?: string; role?: string }; owner?: NodeOwner | null }[] =
      Array.isArray(body) ? body : body?.nodes ?? [];
    const hit = nodes.find((n) => n.id === nodeId);
    if (!hit) return null;
    if (hit.owner) return hit.owner;
    if (hit.type === "owner" && hit.id !== undefined && hit.name) {
      return { id: hit.id, name: hit.name, email: hit.attrs?.email ?? null, role: hit.attrs?.role ?? null };
    }
    return null;
  } catch {
    return null;
  }
}
