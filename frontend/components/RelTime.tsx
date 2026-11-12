"use client";

import type { ReactNode } from "react";
import { useLang } from "@/lib/lang";
import { absoluteTime, relativeTime, useNow } from "@/lib/time";
import { Bi } from "./Bi";

/**
 * "3 minutes ago" in both languages with the exact date and time on hover
 * (title) and in the <time> element. null renders `never` (default "Never").
 * Re-renders every 30 s so the text stays honest; the width can change by a
 * few characters only, so place it in a flexible row.
 */
export function RelTime({ iso, never, className }: { iso: string | null | undefined; never?: ReactNode; className?: string }) {
  const now = useNow(30_000);
  const lang = useLang();
  const rel = relativeTime(iso, now);
  if (!rel) return <span className={className}>{never ?? <Bi en="Never" ar="لم يحدث بعد" />}</span>;
  return (
    <time className={className} dateTime={iso ?? undefined} title={absoluteTime(iso, lang)}>
      <Bi en={rel.en} ar={rel.ar} />
    </time>
  );
}
