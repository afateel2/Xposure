const BACKEND_URL = process.env.BACKEND_URL;

export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  if (!BACKEND_URL) {
    return Response.json({ detail: "BACKEND_URL not configured" }, { status: 502 });
  }
  const { id } = await params;
  try {
    const res = await fetch(`${BACKEND_URL}/changes/${id}`, {
      signal: AbortSignal.timeout(15_000),
      cache: "no-store",
    });
    return Response.json(await res.json(), { status: res.status });
  } catch {
    return Response.json({ detail: "backend unreachable" }, { status: 502 });
  }
}
