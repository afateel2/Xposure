import { proxyToBackend } from "@/lib/proxy";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  // The dismissal reason travels in the body; an empty body is passed on as
  // "no body" so the backend answers with its own clear 422.
  const body = await request.text();
  return proxyToBackend(request, `/actions/${id}/dismiss`, { method: "POST", body: body || undefined, timeoutMs: 15_000 });
}
