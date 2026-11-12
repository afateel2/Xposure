"use client";

import { useEffect, useState } from "react";

/**
 * Real reviewer identity (backend/app/auth.py), replacing the old
 * unauthenticated "who am I" localStorage convenience (lib/whoami.ts,
 * kept only as a display-name default now, see Header.tsx). A session
 * cookie, set by POST /auth/login, is forwarded by every proxy route
 * (app/api/[...path]/route.ts and lib/proxy.ts); fetch() here always
 * passes credentials: "include" so the browser sends it back.
 */
export interface AuthUser {
  id: number;
  email: string;
  name_en: string;
  name_ar: string;
  role: "admin" | "reviewer" | string;
  job_title_en: string | null;
  job_title_ar: string | null;
}

export interface MeResult {
  authenticated: boolean;
  user: AuthUser | null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { credentials: "include", cache: "no-store", ...init });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = (data && typeof data === "object" && "detail" in data ? (data as { detail?: string }).detail : null)
      ?? "Request failed. | فشل الطلب.";
    throw new Error(detail);
  }
  return data as T;
}

export function fetchMe(): Promise<MeResult> {
  return request<MeResult>("/api/auth/me");
}

export function login(email: string, password: string): Promise<MeResult> {
  return request<MeResult>("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
}

export function logout(): Promise<MeResult> {
  return request<MeResult>("/api/auth/logout", { method: "POST" });
}

type Listener = () => void;
let current: MeResult = { authenticated: false, user: null };
let loaded = false;
const listeners = new Set<Listener>();

function notify() {
  listeners.forEach((l) => l());
}

async function ensureLoaded() {
  if (loaded) return;
  loaded = true;
  try {
    current = await fetchMe();
  } catch {
    current = { authenticated: false, user: null };
  }
  notify();
}

/** Call after a successful login/logout so every mounted useSession()
 * consumer (the Header's avatar, etc.) updates without a full reload. */
export function setSessionResult(result: MeResult): void {
  current = result;
  loaded = true;
  notify();
}

/** Shared, lazily-loaded session state. Several components mount this
 * (Header, the login page's "already signed in" redirect); it fetches
 * GET /auth/me at most once per page load, not once per consumer. */
export function useSession(): { authenticated: boolean; user: AuthUser | null; loading: boolean } {
  const [, setTick] = useState(0);
  useEffect(() => {
    const listener = () => setTick((t) => t + 1);
    listeners.add(listener);
    ensureLoaded();
    return () => {
      listeners.delete(listener);
    };
  }, []);
  return { authenticated: current.authenticated, user: current.user, loading: !loaded };
}

export function displayName(user: AuthUser, lang: "en" | "ar"): string {
  return lang === "ar" ? user.name_ar : user.name_en;
}
