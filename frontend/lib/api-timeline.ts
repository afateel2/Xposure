import { ApiError, splitDetail } from "./api-erp";

export type TimelineSeverity = "info" | "success" | "warning" | "danger";

/** One step of a change's lifecycle (mirrors backend/app/visibility/schemas.py TimelineItemOut). */
export interface TimelineItem {
  ts: string;
  kind: string;
  severity: TimelineSeverity;
  /** Lucide icon name in kebab-case (for example "git-compare"). */
  icon?: string;
  text_en: string;
  text_ar: string;
  detail_en?: string | null;
  detail_ar?: string | null;
  actor: string | null;
  action_id: number | null;
  event?: string;
  audit_id?: number | null;
  status_after?: string | null;
}

export interface ChangeTimeline {
  change_id: number;
  items: TimelineItem[];
}

/**
 * GET /changes/{id}/timeline. Throws ApiError; status 404 means this server
 * has no timeline route (the UI then shows an honest empty state).
 */
export async function getChangeTimeline(id: number): Promise<ChangeTimeline> {
  const res = await fetch(`/api/changes/${id}/timeline`, { cache: "no-store" });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const { en, ar } = splitDetail(body?.detail, `GET /api/changes/${id}/timeline failed: ${res.status}`);
    throw new ApiError(res.status, en, ar);
  }
  const body = await res.json();
  // Accept both a bare list and the { items: [...] } envelope.
  const items: TimelineItem[] = Array.isArray(body) ? body : Array.isArray(body?.items) ? body.items : [];
  return { change_id: id, items };
}
