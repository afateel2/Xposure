"use client";

import { Bi } from "@/components/Bi";
import { absoluteTime, parseTs, relativeTime, useNow } from "@/lib/time";
import { useLang } from "@/lib/lang";

/**
 * "3 hours ago" that stays honest (re-renders every 30 s) with the absolute
 * date and time in the tooltip and the machine-readable value in dateTime.
 * Set `withAbsolute` to print the absolute time next to it.
 */
export function RelTime({
  value, prefixEn, prefixAr, withAbsolute, className,
}: {
  value: string | null | undefined;
  prefixEn?: string;
  prefixAr?: string;
  withAbsolute?: boolean;
  className?: string;
}) {
  const now = useNow(30_000);
  const lang = useLang();
  const ms = parseTs(value);
  const rel = relativeTime(value, now);
  if (ms == null || !rel) return null;
  const abs = absoluteTime(value, lang);
  return (
    <time className={className} dateTime={new Date(ms).toISOString()} title={abs}>
      <Bi en={`${prefixEn ? `${prefixEn} ` : ""}${rel.en}`} ar={`${prefixAr ? `${prefixAr} ` : ""}${rel.ar}`} />
      {withAbsolute && <span className="chg-abs tabular"> ({abs})</span>}
    </time>
  );
}
