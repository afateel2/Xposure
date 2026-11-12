/**
 * Small fetch helper for the demo run and facility profile features. Every call goes through the generic proxy at /api/*. Errors keep
 * the backend's own `detail` text so the UI can show the real reason.
 */
export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
  /** The route does not exist or the backend cannot be reached (older backend, not started). */
  get unavailable(): boolean {
    return this.status === 404 || this.status === 502 || this.status === 503 || this.status === 0;
  }
}

function detailOf(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string" && d) return d;
    if (Array.isArray(d)) {
      const msgs = d.map((x) => (x && typeof x === "object" && "msg" in x ? String((x as { msg: unknown }).msg) : "")).filter(Boolean);
      if (msgs.length) return msgs.join("; ");
    }
  }
  return `HTTP ${status}`;
}

export async function apiJson<T>(path: string, init?: RequestInit & { signal?: AbortSignal }): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, { cache: "no-store", ...init });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(0, "The backend cannot be reached.");
  }
  const body: unknown = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, detailOf(body, res.status));
  return body as T;
}

/** Turns any thrown value into the text to show. */
export function errorText(err: unknown): string {
  if (err instanceof ApiError) return err.detail;
  if (err instanceof Error) return err.message;
  return String(err);
}
