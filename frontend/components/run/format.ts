import type { BiText } from "@/lib/time";
import { parseTs } from "@/lib/time";

/** "1:05" clock for a duration in ms (always Latin digits, left to right). */
export function clock(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}

/**
 * Human duration in both languages. Backend stage times have one second of
 * resolution, so anything shorter is shown as "under 1 s" instead of a
 * made-up decimal.
 */
export function durationText(ms: number): BiText {
  const s = Math.max(0, Math.floor(ms / 1000));
  if (s < 1) return { en: "<1 s", ar: "أقل من ثانية" };
  if (s < 60) return { en: `${s} s`, ar: `${s} ث` };
  const m = Math.floor(s / 60);
  return { en: `${m} min ${s % 60} s`, ar: `${m} د ${s % 60} ث` };
}

/** Elapsed ms between two backend timestamps; `end` defaults to `now`. Null when the start is unknown. */
export function elapsedMs(start: string | null | undefined, end: string | null | undefined, now: number): number | null {
  const a = parseTs(start);
  if (a == null) return null;
  const b = parseTs(end) ?? now;
  return Math.max(0, b - a);
}

export function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function fmtInt(n: number): string {
  return n.toLocaleString("en-US");
}

/** "ECC-2:2024" from a regulation code and a backend version label like "2-2024". */
export function versionName(regulation: string | null | undefined, label: string | null | undefined): string {
  const l = (label ?? "").replace("-", ":");
  return regulation ? `${regulation.toUpperCase()}-${l}` : l;
}

export function kb(bytes: number): string {
  return `${(bytes / 1024).toFixed(bytes >= 10 * 1024 ? 0 : 1)} KB`;
}
