const BACKEND_URL = process.env.BACKEND_URL;

export async function GET() {
  if (!BACKEND_URL) {
    return Response.json({ detail: "BACKEND_URL not configured" }, { status: 502 });
  }
  try {
    const res = await fetch(`${BACKEND_URL}/agent/eval-summary`, {
      signal: AbortSignal.timeout(15_000),
      cache: "no-store",
    });
    return Response.json(await res.json(), { status: res.status });
  } catch {
    return Response.json({ detail: "backend unreachable" }, { status: 502 });
  }
}
