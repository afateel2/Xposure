import { proxyToBackend } from "@/lib/proxy";

export async function GET(request: Request) {
  return proxyToBackend(request, "/settings/policy", { method: "GET", timeoutMs: 15_000 });
}

export async function PUT(request: Request) {
  const body = await request.text();
  return proxyToBackend(request, "/settings/policy", { method: "PUT", body, timeoutMs: 15_000 });
}
