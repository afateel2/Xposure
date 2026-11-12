"use client";

import Link from "next/link";
import { CalendarClock, CircleCheck, Clock, TriangleAlert } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Bi } from "@/components/Bi";
import { RelTime } from "@/components/RelTime";
import { BrandMotif, Icon } from "@/components/ui";
import { useLang } from "@/lib/lang";
import { absoluteTime } from "@/lib/time";
import type { OverviewSource, SourceStatus } from "@/lib/types-visibility";

/**
 * Each status has its own icon and words as well as its colour, so "in sync",
 * "stale" and "needs attention" can never be mistaken for one another, and a
 * planned regulator never looks monitored.
 */
const STATUS_VIEW: Record<SourceStatus, { tone: string; icon: LucideIcon; en: string; ar: string }> = {
  ok: { tone: "success", icon: CircleCheck, en: "In sync", ar: "متزامن" },
  attention: { tone: "warning", icon: TriangleAlert, en: "Needs attention", ar: "يتطلب انتباهًا" },
  stale: { tone: "warning", icon: Clock, en: "Not checked recently", ar: "لم يُفحص مؤخرًا" },
  planned: { tone: "muted", icon: CalendarClock, en: "Planned", ar: "مخطط له" },
};

const REASON_HINT: Record<string, { en: string; ar: string }> = {
  conflict: { en: "A source file conflicts with an ingested version.", ar: "ملف مصدر يتعارض مع إصدار جرى إدخاله." },
  overdue_actions: { en: "Some actions are past their due date.", ar: "بعض الإجراءات تجاوزت موعدها." },
  never_checked: { en: "This source has never been checked.", ar: "لم يُفحص هذا المصدر من قبل." },
  not_checked_recently: { en: "The last check is older than the freshness limit.", ar: "آخر فحص أقدم من حدّ الحداثة." },
};

function StatusChip({ status }: { status: SourceStatus }) {
  const v = STATUS_VIEW[status];
  return (
    <span className={`dash-chip tone-${v.tone}`}>
      <Icon icon={v.icon} size={13} />
      <Bi en={v.en} ar={v.ar} />
    </span>
  );
}

function MonitoredCard({ s }: { s: OverviewSource }) {
  const lang = useLang();
  const hint = s.status !== "ok" ? REASON_HINT[s.status_reason] : undefined;
  return (
    <li className={`dash-src status-${s.status}`}>
      <div className="dash-src-head">
        <div className="dash-src-name">
          <b><bdi>{s.regulator_code.toUpperCase()}</bdi></b>
          <span><Bi en={s.title_en ?? s.name_en} ar={s.title_ar ?? s.name_ar} /></span>
        </div>
        <StatusChip status={s.status} />
      </div>
      <dl className="dash-src-facts">
        <div>
          <dt><Bi en="Latest version" ar="أحدث إصدار" /></dt>
          <dd className="mono"><bdi>{s.latest_version ?? "-"}</bdi></dd>
        </div>
        <div>
          <dt><Bi en="Last checked" ar="آخر فحص" /></dt>
          <dd><RelTime iso={s.last_checked_at} never={<Bi en="Never checked" ar="لم يُفحص بعد" />} /></dd>
        </div>
        <div className="is-key">
          <dt><Bi en="Last change" ar="آخر تغيير" /></dt>
          <dd title={absoluteTime(s.last_change_at, lang)}>
            <RelTime iso={s.last_change_at} never={<Bi en="No change recorded" ar="لا تغيير مسجَّل" />} />
          </dd>
        </div>
        <div>
          <dt><Bi en="Open changes" ar="تغييرات مفتوحة" /></dt>
          <dd className="tabular">
            <Link href="/changes" className="dash-inline-link">{s.open_changes}</Link>
          </dd>
        </div>
      </dl>
      {hint && <p className="dash-src-hint"><Icon icon={TriangleAlert} size={13} /><Bi en={hint.en} ar={hint.ar} /></p>}
    </li>
  );
}

function PlannedCard({ s }: { s: OverviewSource }) {
  return (
    <li className="dash-src is-planned">
      <div className="dash-src-head">
        <div className="dash-src-name">
          <b><bdi>{s.regulator_code.toUpperCase()}</bdi></b>
          <span><Bi en={s.name_en} ar={s.name_ar} /></span>
        </div>
      </div>
      {s.scope_en && <p className="dash-src-scope"><Bi en={s.scope_en} ar={s.scope_ar ?? s.scope_en} /></p>}
      <StatusChip status="planned" />
    </li>
  );
}

/** Per-regulator cards: monitored sources first, planned regulators muted and clearly not monitored. */
export function SourceCards({ sources }: { sources: OverviewSource[] | null }) {
  if (!sources) return <BrandMotif variant="spinner" compact title={<Bi en="Loading sources" ar="جارٍ تحميل المصادر" />} />;
  const monitored = sources.filter((s) => !s.planned);
  const planned = sources.filter((s) => s.planned);
  if (sources.length === 0) {
    return <BrandMotif compact title={<Bi en="No regulatory sources yet" ar="لا توجد مصادر تنظيمية بعد" />} />;
  }
  return (
    <div className="dash-sources">
      {monitored.length === 0 ? (
        <BrandMotif compact title={<Bi en="No source is monitored yet" ar="لا يوجد مصدر مراقَب بعد" />} hint={<Bi en="Run the agent to ingest the first regulation version." ar="شغّل الوكيل لإدخال أول إصدار من النظام." />} />
      ) : (
        <ul className="dash-src-list">{monitored.map((s) => <MonitoredCard key={s.code} s={s} />)}</ul>
      )}
      {planned.length > 0 && (
        <>
          <h4 className="dash-sub"><Bi en="Planned, not monitored yet" ar="مخطط لها، وغير مراقَبة بعد" /></h4>
          <ul className="dash-src-list is-planned">{planned.map((s) => <PlannedCard key={s.code} s={s} />)}</ul>
        </>
      )}
    </div>
  );
}
