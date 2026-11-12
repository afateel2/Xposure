import { useEffect, useState } from "react";
import type { Lang } from "./lang";

/** A bilingual string pair, rendered with <Bi en ar /> or picked with pick(). */
export interface BiText {
  en: string;
  ar: string;
}

export function pick(text: BiText, lang: Lang): string {
  return lang === "ar" ? text.ar : text.en;
}

/**
 * Parses a backend timestamp. The API sends timezone-aware UTC ("...Z"), but a
 * few values (ERP synced_at) may come without a zone: those are UTC too.
 * Returns null for null, undefined and unparseable input.
 */
export function parseTs(value: string | number | Date | null | undefined): number | null {
  if (value == null || value === "") return null;
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value.getTime();
  if (typeof value === "number") return value;
  const hasZone = /(Z|[+-]\d{2}:?\d{2})$/i.test(value);
  const hasTime = value.includes("T");
  const ms = Date.parse(hasTime && !hasZone ? `${value}Z` : value);
  return Number.isNaN(ms) ? null : ms;
}

const MIN = 60_000;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;

// Latin digits in Arabic text, as everywhere else in the app.
const RTF_AR = typeof Intl !== "undefined" ? new Intl.RelativeTimeFormat("ar-u-nu-latn", { numeric: "always" }) : null;
const RTF_EN = typeof Intl !== "undefined" ? new Intl.RelativeTimeFormat("en", { numeric: "always" }) : null;

function rel(value: number, unit: Intl.RelativeTimeFormatUnit): BiText {
  return {
    en: RTF_EN ? RTF_EN.format(value, unit) : `${value} ${unit}`,
    ar: RTF_AR ? RTF_AR.format(value, unit) : `${value} ${unit}`,
  };
}

/**
 * "3 minutes ago" / "قبل 3 دقائق". Whole units, rounded DOWN (never claims to
 * be fresher than it is), no fake precision: under a minute is "just now",
 * beyond 60 days it becomes months. Null means "never". Future timestamps
 * (clock skew) are treated as "just now".
 */
export function relativeTime(value: string | number | Date | null | undefined, now: number = Date.now()): BiText | null {
  const ms = parseTs(value);
  if (ms == null) return null;
  const diff = now - ms;
  if (diff < MIN) return { en: "Just now", ar: "قبل لحظات" };
  if (diff < HOUR) return rel(-Math.floor(diff / MIN), "minute");
  if (diff < DAY) return rel(-Math.floor(diff / HOUR), "hour");
  if (diff < 14 * DAY) return rel(-Math.floor(diff / DAY), "day");
  if (diff < 60 * DAY) return rel(-Math.floor(diff / (7 * DAY)), "week");
  return rel(-Math.floor(diff / (30 * DAY)), "month");
}

/** Whole hours since the timestamp, or null when unknown. */
export function ageHours(value: string | number | Date | null | undefined, now: number = Date.now()): number | null {
  const ms = parseTs(value);
  return ms == null ? null : (now - ms) / HOUR;
}

/** Absolute date and time in the viewer's zone, Gregorian, Latin digits. */
export function absoluteTime(value: string | number | Date | null | undefined, lang: Lang): string {
  const ms = parseTs(value);
  if (ms == null) return "";
  const locale = lang === "ar" ? "ar-SA-u-nu-latn-ca-gregory" : "en-GB";
  return new Date(ms).toLocaleString(locale, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function absoluteTimeBi(value: string | number | Date | null | undefined): BiText {
  return { en: absoluteTime(value, "en"), ar: absoluteTime(value, "ar") };
}

/** Short absolute date only (for due dates). Accepts "YYYY-MM-DD". */
export function absoluteDate(value: string | null | undefined, lang: Lang): string {
  if (!value) return "";
  const ms = /^\d{4}-\d{2}-\d{2}$/.test(value) ? Date.parse(`${value}T12:00:00`) : parseTs(value);
  if (ms == null || Number.isNaN(ms)) return "";
  const locale = lang === "ar" ? "ar-SA-u-nu-latn-ca-gregory" : "en-GB";
  return new Date(ms).toLocaleDateString(locale, { day: "numeric", month: "short", year: "numeric" });
}

/** Due-date wording from the backend's days_left (negative = overdue). */
export function dueText(daysLeft: number | null | undefined): BiText | null {
  if (daysLeft == null) return null;
  if (daysLeft < 0) {
    const n = Math.abs(daysLeft);
    return { en: `Overdue by ${n} ${n === 1 ? "day" : "days"}`, ar: `متأخرة ${arDays(n)}` };
  }
  if (daysLeft === 0) return { en: "Due today", ar: "تستحق اليوم" };
  if (daysLeft === 1) return { en: "Due tomorrow", ar: "تستحق غدًا" };
  return { en: `Due in ${daysLeft} days`, ar: `تستحق خلال ${arDays(daysLeft)}` };
}

/** Arabic day count with the right plural form: يوم، يومان، 3 أيام، 11 يومًا. */
function arDays(n: number): string {
  if (n === 1) return "يومًا واحدًا";
  if (n === 2) return "يومين";
  if (n >= 3 && n <= 10) return `${n} أيام`;
  return `${n} يومًا`;
}

/** Re-renders the caller every `intervalMs` so relative times stay honest. */
export function useNow(intervalMs = 30_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}
