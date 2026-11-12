/**
 * POST /sources/check-live, GET /sources/check-live/last (backend
 * app/watcher.py). A real, on-demand check against the regulator's own
 * public page, requires sign-in (backend/app/auth.py), never run
 * automatically by this frontend.
 */

export interface LiveCheckResult {
  regulator: string;
  regulation: string;
  checked_at: string;
  page_url: string;
  live_version_label: string;
  pdf_url: string;
  known_versions: string[];
  status: "new_version_available" | "matches_known" | "content_conflict";
  message_en: string;
  message_ar: string;
  file_sha256: string | null;
  from_cache: boolean;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function handle<T>(res: Response): Promise<T> {
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = (data && typeof data === "object" && "detail" in data ? (data as { detail?: string }).detail : null)
      ?? `Request failed (${res.status}).`;
    throw new ApiError(res.status, detail);
  }
  return data as T;
}

export async function checkLivePortal(regulator: string, regulation: string): Promise<LiveCheckResult> {
  const res = await fetch(`/api/sources/check-live?regulator=${encodeURIComponent(regulator)}&regulation=${encodeURIComponent(regulation)}`, {
    method: "POST",
    credentials: "include",
  });
  return handle<LiveCheckResult>(res);
}

export async function lastLiveCheck(regulator: string, regulation: string): Promise<{ checked: boolean } & Partial<LiveCheckResult>> {
  const res = await fetch(`/api/sources/check-live/last?regulator=${encodeURIComponent(regulator)}&regulation=${encodeURIComponent(regulation)}`, {
    credentials: "include",
    cache: "no-store",
  });
  return handle(res);
}
