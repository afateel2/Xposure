"use client";

import { CalendarClock, TriangleAlert } from "lucide-react";
import { Bi } from "@/components/Bi";
import { Icon } from "@/components/ui";
import { absoluteDate, dueText } from "@/lib/time";
import { useLang } from "@/lib/lang";

function daysUntil(isoDate: string): number {
  const [y, m, d] = isoDate.split("-").map(Number);
  const due = new Date(y, (m ?? 1) - 1, d ?? 1).getTime();
  const today = new Date();
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime();
  return Math.round((due - start) / 86_400_000);
}

/**
 * Due date with the overdue treatment: danger colour plus a warning icon
 * (never colour alone). Backend due dates exist only when the regulator stated
 * one (effective date plus grace), so a missing one says so instead of
 * inventing a deadline.
 */
export function DueLabel({ dueDate, overdue, compact }: { dueDate: string | null; overdue: boolean; compact?: boolean }) {
  const lang = useLang();
  if (!dueDate) {
    return (
      <span className="chg-due is-none">
        <Icon icon={CalendarClock} size={14} />
        {compact ? <Bi en="No deadline" ar="بلا موعد نهائي" /> : <Bi en="No stated deadline" ar="لا يوجد موعد نهائي معلن" />}
      </span>
    );
  }
  const text = dueText(daysUntil(dueDate));
  const abs = absoluteDate(dueDate, lang);
  const soon = !overdue && daysUntil(dueDate) >= 0 && daysUntil(dueDate) <= 7;
  return (
    <span className={`chg-due${overdue ? " is-overdue" : soon ? " is-soon" : ""}`} title={abs}>
      <Icon icon={overdue ? TriangleAlert : CalendarClock} size={14} />
      {text && <Bi en={text.en} ar={text.ar} />}
      {!compact && <span className="chg-due-abs tabular">{abs}</span>}
    </span>
  );
}
