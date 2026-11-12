const BACKEND_URL = process.env.BACKEND_URL;

// Generic passthrough to the FastAPI backend for every endpoint that has no
// dedicated route file under app/api. More specific route files (changes,
// actions, exports...) keep precedence, so nothing existing changes. New
// features only need a backend route: no per-endpoint proxy file required.
async function proxy(request: Request, { params }: { params: Promise<{ path: string[] }> }) {
  if (!BACKEND_URL) {
    return Response.json({ detail: "BACKEND_URL not configured" }, { status: 502 });
  }
  const { path } = await params;
  const { search } = new URL(request.url);
  const target = `${BACKEND_URL}/${path.map(encodeURIComponent).join("/")}${search}`;
  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  // Session auth (app/auth.py) rides the xposure_session cookie. This is a
  // server-to-server fetch, so the browser's cookie is never sent
  // automatically; forward it by hand both ways, Cookie in and Set-Cookie
  // back, or every signed-in request would silently look signed-out to the
  // backend.
  const cookie = request.headers.get("cookie");
  const headers: Record<string, string> = {};
  if (hasBody) headers["Content-Type"] = request.headers.get("content-type") ?? "application/json";
  if (cookie) headers["Cookie"] = cookie;
  try {
    const res = await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? await request.text() : undefined,
      signal: AbortSignal.timeout(120_000),
      cache: "no-store",
    });
    const outHeaders = new Headers();
    for (const name of ["content-type", "content-disposition"]) {
      const value = res.headers.get(name);
      if (value) outHeaders.set(name, value);
    }
    // fetch() exposes multiple Set-Cookie values as one header on getSetCookie();
    // a plain res.headers.get("set-cookie") would only ever return the first.
    for (const value of res.headers.getSetCookie?.() ?? []) {
      outHeaders.append("Set-Cookie", value);
    }
    return new Response(res.body, { status: res.status, headers: outHeaders });
  } catch {
    return Response.json({ detail: "backend unreachable" }, { status: 502 });
  }
}

export { proxy as GET, proxy as POST, proxy as PUT, proxy as PATCH, proxy as DELETE };
