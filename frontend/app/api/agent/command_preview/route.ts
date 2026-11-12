const BACKEND_URL = process.env.BACKEND_URL;

export async function POST(request: Request) {
  if (!BACKEND_URL) {
    return Response.json({ detail: "BACKEND_URL not configured" }, { status: 502 });
  }
  const body = await request.text();
  try {
    const res = await fetch(`${BACKEND_URL}/agent/command_preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      signal: AbortSignal.timeout(15_000),
    });
    return Response.json(await res.json(), { status: res.status });
  } catch {
    return Response.json({ detail: "backend unreachable" }, { status: 502 });
  }
}
