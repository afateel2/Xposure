import { proxyToBackend } from "@/lib/proxy";

export async function POST(request: Request) {
  const body = await request.text();
  return proxyToBackend(request, "/actions/bulk", { method: "POST", body, timeoutMs: 15_000 });
}
