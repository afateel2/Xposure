const BACKEND_URL = process.env.BACKEND_URL;

export async function GET() {
  if (!BACKEND_URL) {
    return Response.json({ status: "offline", ready: false }, { status: 200 });
  }
  try {
    // Backend's own /health can legitimately take up to ~5.3s (a 5s hard
    // deadline on the LLM reachability probe, see app/llm.py's probe(),
    // plus DB/Qdrant overhead) when the LLM provider is slow to respond.
    // This timeout must stay safely above that, or a healthy-but-slow
    // backend reads as "offline" purely from the two timeouts racing.
    const res = await fetch(`${BACKEND_URL}/health`, {
      signal: AbortSignal.timeout(8_000),
      cache: "no-store",
    });
    if (!res.ok) throw new Error(String(res.status));
    return Response.json(await res.json());
  } catch {
    return Response.json({ status: "offline", ready: false }, { status: 200 });
  }
}
