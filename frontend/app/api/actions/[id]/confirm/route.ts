import { proxyToBackend } from "@/lib/proxy";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return proxyToBackend(request, `/actions/${id}/confirm`, { method: "POST", timeoutMs: 15_000 });
}
