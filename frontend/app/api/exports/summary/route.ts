const BACKEND_URL = process.env.BACKEND_URL;

// Binary export proxy, same shape as app/api/changes/[id]/export/pdf: streams
// the backend's raw PDF body and headers through untouched.
export async function GET(request: Request) {
  if (!BACKEND_URL) {
    return Response.json({ detail: "BACKEND_URL not configured" }, { status: 502 });
  }
  const { search } = new URL(request.url);
  try {
    const res = await fetch(`${BACKEND_URL}/exports/summary${search}`, {
      signal: AbortSignal.timeout(30_000),
      cache: "no-store",
    });
    const headers = new Headers();
    const contentType = res.headers.get("content-type");
    const disposition = res.headers.get("content-disposition");
    if (contentType) headers.set("content-type", contentType);
    if (disposition) headers.set("content-disposition", disposition);
    return new Response(res.body, { status: res.status, headers });
  } catch {
    return Response.json({ detail: "backend unreachable" }, { status: 502 });
  }
}
