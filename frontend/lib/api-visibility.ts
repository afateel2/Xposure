import type { ErpStatus } from "./types-shared";
import type {
  ActivityPage, AgentState, AuditActorInfo, AuditEventInfo, AuditPage, ErpSyncResult, NewCount, Overview, TasksPage,
} from "./types-visibility";

/** Error carrying the HTTP status so pages can tell "route missing" (404) from "backend down" (502). */
export class ApiError extends Error {
  status: number;
  /** Bilingual message when the backend sent one (ERP errors do). */
  messageEn?: string;
  messageAr?: string;
  constructor(status: number, message: string, bi?: { en?: string; ar?: string }) {
    super(message);
    this.status = status;
    this.messageEn = bi?.en;
    this.messageAr = bi?.ar;
  }
}

function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, { cache: "no-store", ...init });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(0, "network");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const d = body?.detail;
    const text = typeof d === "string" ? d : typeof d?.message_en === "string" ? d.message_en : "";
    throw new ApiError(res.status, text || `${init?.method ?? "GET"} ${path} failed: ${res.status}`, {
      en: typeof d?.message_en === "string" ? d.message_en : undefined,
      ar: typeof d?.message_ar === "string" ? d.message_ar : undefined,
    });
  }
  return res.json() as Promise<T>;
}

export const getOverview = (signal?: AbortSignal) => request<Overview>("/overview", { signal });

export const getAgentState = (signal?: AbortSignal) => request<AgentState>("/agent/state", { signal });

export const getActivity = (params: { limit?: number; sinceReset?: boolean; kind?: string; beforeId?: number } = {}, signal?: AbortSignal) =>
  request<ActivityPage>(
    `/activity${qs({ limit: params.limit ?? 50, since_reset: params.sinceReset, kind: params.kind, before_id: params.beforeId })}`,
    { signal },
  );

export const getNewCount = (since: string, signal?: AbortSignal) =>
  request<NewCount>(`/changes/new-count${qs({ since })}`, { signal });

export interface TasksQuery {
  status?: string;
  assigned?: boolean;
  limit?: number;
  offset?: number;
}

export const getTasks = (q: TasksQuery = {}, signal?: AbortSignal) =>
  request<TasksPage>(`/tasks${qs({ status: q.status, assigned: q.assigned, limit: q.limit ?? 200, offset: q.offset })}`, { signal });

export interface AuditQuery {
  limit?: number;
  offset?: number;
  event?: string;
  actor?: string;
  since?: string;
}

export const getAudit = (q: AuditQuery = {}, signal?: AbortSignal) =>
  request<AuditPage>(`/audit${qs({ limit: q.limit ?? 50, offset: q.offset, event: q.event, actor: q.actor, since: q.since })}`, { signal });

export const getAuditEvents = (signal?: AbortSignal) =>
  request<{ events: AuditEventInfo[] }>("/audit/events", { signal }).then((r) => r.events);

export const getAuditActors = (signal?: AbortSignal) =>
  request<{ actors: AuditActorInfo[] }>("/audit/actors", { signal }).then((r) => r.actors);

export const getErpStatus = (signal?: AbortSignal) => request<ErpStatus>("/erp/status", { signal });

export const syncErp = () => request<ErpSyncResult>("/erp/sync", { method: "POST" });
