const WHOAMI_STORAGE_KEY = "xposure_whoami";

/**
 * A local, unauthenticated "who am I" convenience for the "assigned to
 * me" filter — this app has no login system at all (every server-side
 * actor is literally the string "user:web"), so this is deliberately
 * scoped as a per-browser filtering convenience, not identity. Same
 * SSR-safe try/catch shape as lib/lang.ts's getStoredLang/setStoredLang.
 */
export function getStoredWhoAmI(): string {
  if (typeof window === "undefined") return "";
  try {
    return localStorage.getItem(WHOAMI_STORAGE_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setStoredWhoAmI(name: string): void {
  try {
    localStorage.setItem(WHOAMI_STORAGE_KEY, name);
  } catch {
    // localStorage unavailable (private mode) or quota exceeded — best-effort only
  }
}
