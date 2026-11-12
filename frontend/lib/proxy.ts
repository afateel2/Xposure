/**
 * Shared body for the dedicated (non-catch-all) backend proxy routes under
 * app/api/** (approve, dismiss, delegate, confirm, undo, bulk, settings
 * policy, ...). Mirrors app/api/[...path]/route.ts's cookie handling:
 * session auth (backend/app/auth.py) rides the xposure_session cookie,
 * and a server-to-server fetch never carries the browser's cookie
 * automatically, so it has to be forwarded by hand, Cookie in and
 * Set-Cookie back (relevant for /auth/login and /auth/logout specifically,
 * forwarded here too for symmetry even though most callers only read it).
 */

const BACKEND_URL = process.env.BACKEND_URL;

export async function proxyToBackend(
  request: Request,
  backendPath: string,
  options: { method: string; body?: string; timeoutMs?: number } = { method: "POST" }
): Promise<Response> {
  if (!BACKEND_URL) {
    return Response.json({ detail: "BACKEND_URL not configured" }, { status: 502 });
  }
  const cookie = request.headers.get("cookie");
  const headers: Record<string, string> = {};
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (cookie) headers["Cookie"] = cookie;
  try {
    const res = await fetch(`${BACKEND_URL}${backendPath}`, {
      method: options.method,
      headers,
      body: options.body,
      signal: AbortSignal.timeout(options.timeoutMs ?? 120_000),
      cache: "no-store",
    });
    const outHeaders = new Headers();
    for (const value of res.headers.getSetCookie?.() ?? []) {
      outHeaders.append("Set-Cookie", value);
    }
    const data = await res.json().catch(() => null);
    return Response.json(data, { status: res.status, headers: outHeaders });
  } catch {
    return Response.json({ detail: "backend unreachable" }, { status: 502 });
  }
}
