const BACKEND_URL = process.env.BACKEND_URL;

export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  if (!BACKEND_URL) {
    return Response.json({ detail: "BACKEND_URL not configured" }, { status: 502 });
  }
  const { id } = await params;
  try {
    const res = await fetch(`${BACKEND_URL}/changes/${id}/export/excel`, {
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
