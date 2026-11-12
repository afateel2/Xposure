"use client";

import Link from "next/link";
import { Fragment, Suspense, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ChevronDown, ChevronLeft, ChevronRight, Download, Lock, RotateCcw } from "lucide-react";
import { ActivityGlyph } from "@/components/ActivityFeed";
import { Bi } from "@/components/Bi";
import { RelTime } from "@/components/RelTime";
import { BrandMotif, Button, Card, DataTable, Field, Icon, Input, PageHeader, Segmented, Select, useToast } from "@/components/ui";
import { ApiError, getAudit, getAuditActors, getAuditEvents } from "@/lib/api-visibility";
import { t as pick, useLang } from "@/lib/lang";
import { absoluteTime } from "@/lib/time";
import { usePoll } from "@/lib/use-poll";
import type { AuditEventInfo, AuditPage, AuditRow } from "@/lib/types-visibility";

const PAGE_SIZE = 50;

type View = "all" | "decisions";

// "Decisions and actions": what people and the agent DID to the company, without the
// per-clause pipeline bookkeeping (created, prioritised, impact, webhook and stage rows).
const DECISION_KINDS = new Set(["delegate", "confirm", "undo", "effect", "export"]);
const DECISION_EVENTS = new Set([
  "action_approved", "action_dismissed", "action_auto_executed", "bulk_action_applied", "action_status_reverted",
  "demo_reset", "scan_requested", "scan_completed", "scan_failed", "run_paused_for_human_review", "source_ingested",
]);
const decisionEvents = (events: AuditEventInfo[]): string[] =>
  events.filter((e) => DECISION_EVENTS.has(e.event) || DECISION_KINDS.has(e.kind)).map((e) => e.event);

function csvCell(value: unknown): string {
  let s = value == null ? "" : typeof value === "string" ? value : JSON.stringify(value);
  // Neutralise spreadsheet formula injection: audit text can contain user-entered notes.
  if (/^[=+\-@\t\r]/.test(s)) s = `'${s}`;
  return `"${s.replace(/"/g, '""')}"`;
}

function rowsToCsv(rows: AuditRow[]): string {
  const head = ["id", "timestamp_utc", "actor", "event", "ref_type", "ref_id", "summary_en", "summary_ar", "payload_json"];
  const lines = rows.map((r) => [r.id, r.ts, r.actor, r.event, r.ref_type, r.ref_id, r.summary_en, r.summary_ar, r.payload ?? {}].map(csvCell).join(","));
  // BOM so Excel opens the Arabic summaries as UTF-8.
  return `﻿${[head.map(csvCell).join(","), ...lines].join("\r\n")}\r\n`;
}

function changeIdOf(r: AuditRow): number | null {
  if (r.ref_type === "change" && r.ref_id) return r.ref_id;
  const c = r.payload?.change_id;
  return typeof c === "number" ? c : null;
}

function AuditTableRow({ row, label, open, onToggle }: { row: AuditRow; label: { en: string; ar: string } | null; open: boolean; onToggle: () => void }) {
  const lang = useLang();
  const changeId = changeIdOf(row);
  const panelId = `aud-payload-${row.id}`;
  const hasPayload = row.payload != null && Object.keys(row.payload).length > 0;
  return (
    <Fragment>
      <tr className={open ? "aud-open" : ""}>
        <td className="aud-cell-toggle">
          <button
            type="button"
            className="aud-toggle"
            aria-expanded={open}
            aria-controls={panelId}
            onClick={onToggle}
            title={pick(lang, "Show raw payload", "عرض البيانات الخام")}
          >
            <Icon icon={ChevronDown} size={16} className={open ? "is-open" : ""} />
            <span className="sr-only"><Bi en="Show raw payload" ar="عرض البيانات الخام" /></span>
          </button>
        </td>
        <td className="aud-cell-time">
          <RelTime iso={row.ts} className="aud-rel" />
          <span className="aud-abs mono">{absoluteTime(row.ts, lang)}</span>
        </td>
        <td className="mono aud-actor"><bdi>{row.actor}</bdi></td>
        <td className="aud-cell-event">
          <span className="aud-event">
            <ActivityGlyph icon={row.icon} kind={row.kind} severity={row.severity} size={14} />
            <span>
              <span className="aud-event-label">{label ? <Bi en={label.en} ar={label.ar} /> : <bdi className="mono">{row.event}</bdi>}</span>
              {label && <bdi className="aud-event-raw mono">{row.event}</bdi>}
            </span>
          </span>
        </td>
        <td className="aud-cell-summary"><Bi en={row.summary_en} ar={row.summary_ar} /></td>
        <td className="aud-cell-ref">
          {changeId ? (
            <Link href={`/changes/${changeId}`} className="aud-ref mono"><bdi>{`change #${changeId}`}</bdi></Link>
          ) : row.ref_type ? (
            <span className="mono aud-ref-plain"><bdi>{row.ref_id ? `${row.ref_type} #${row.ref_id}` : row.ref_type}</bdi></span>
          ) : (
            <span className="tsk-muted">-</span>
          )}
        </td>
      </tr>
      {open && (
        <tr className="aud-payload-row">
          <td colSpan={6} id={panelId}>
            {hasPayload ? (
              <pre className="aud-payload" dir="ltr" tabIndex={0}>{JSON.stringify(row.payload, null, 2)}</pre>
            ) : (
              <p className="aud-nopayload"><Bi en="This entry has no payload." ar="لا توجد بيانات مرفقة بهذا السجل." /></p>
            )}
          </td>
        </tr>
      )}
    </Fragment>
  );
}

function AuditView() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const lang = useLang();
  const toast = useToast();
  const event = params.get("event") ?? "";
  const actor = params.get("actor") ?? "";
  const since = /^\d{4}-\d{2}-\d{2}$/.test(params.get("since") ?? "") ? (params.get("since") as string) : "";
  const view: View = params.get("view") === "decisions" ? "decisions" : "all";
  const pageNo = Math.max(1, Number.parseInt(params.get("page") ?? "1", 10) || 1);
  const [openIds, setOpenIds] = useState<Set<number>>(new Set());

  function update(patch: Record<string, string>) {
    const sp = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(patch)) {
      if (v && !(k === "page" && v === "1")) sp.set(k, v);
      else sp.delete(k);
    }
    const qs = sp.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }
  const setFilter = (k: "event" | "actor" | "since", v: string) => update({ [k]: v, page: "" });

  const key = `${view}|${event}|${actor}|${since}|${pageNo}`;
  const audit = usePoll<{ key: string; page: AuditPage }>(
    async (signal) => {
      let eventParam = event || undefined;
      if (!eventParam && view === "decisions") eventParam = decisionEvents(await getAuditEvents(signal)).join(",") || undefined;
      const page = await getAudit(
        {
          limit: PAGE_SIZE, offset: (pageNo - 1) * PAGE_SIZE, event: eventParam, actor: actor || undefined,
          since: since ? new Date(`${since}T00:00:00`).toISOString() : undefined,
        },
        signal,
      );
      return { key, page };
    },
    60_000,
    [key],
  );
  const events = usePoll(getAuditEvents, 300_000);
  const actors = usePoll(getAuditActors, 300_000);

  const labelOf = useMemo(() => {
    const m = new Map<string, { en: string; ar: string }>();
    for (const e of events.data ?? []) m.set(e.event, { en: e.label_en, ar: e.label_ar });
    return m;
  }, [events.data]);

  const page = audit.data?.page ?? null;
  const fresh = audit.data?.key === key;
  const total = page?.total ?? 0;
  const from = page && page.items.length ? page.offset + 1 : 0;
  const to = page ? page.offset + page.items.length : 0;
  const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const missing = !page && audit.error instanceof ApiError && audit.error.status === 404;
  const filtered = !!(event || actor || since || view !== "all");

  function exportCsv() {
    if (!page || page.items.length === 0) return;
    const blob = new Blob([rowsToCsv(page.items)], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `xposure-audit-${new Date().toISOString().slice(0, 10)}-page-${pageNo}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast.success(
      <Bi en={`Exported ${page.items.length} rows from this page.`} ar={`تم تصدير ${page.items.length} سجلًا من هذه الصفحة.`} />,
    );
  }

  function toggle(id: number) {
    setOpenIds((cur) => {
      const next = new Set(cur);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const actorList = actors.data ?? [];
  const actorOptions = actor && !actorList.some((a) => a.actor === actor) ? [{ actor, count: 0 }, ...actorList] : actorList;

  return (
    <main className="aud">
      <PageHeader
        title={<Bi en="Audit log" ar="سجل التدقيق" />}
        subtitle={<Bi en="Every decision and every step the agent took, with who did it and when." ar="كل قرار وكل خطوة نفّذها الوكيل، مع من قام بها ومتى." />}
        actions={
          <Button variant="secondary" icon={<Icon icon={Download} size={16} />} disabled={!page || page.items.length === 0} onClick={exportCsv}>
            <Bi en="Export CSV" ar="تصدير CSV" />
          </Button>
        }
      />

      <p className="aud-note">
        <Icon icon={Lock} size={14} />
        <span>
          <Bi
            en="The log is append-only: entries are never edited or deleted. The CSV export contains the rows of the page you are viewing."
            ar="السجل للإضافة فقط: لا تُعدَّل السجلات ولا تُحذف. يتضمن ملف CSV سجلات الصفحة المعروضة حاليًا."
          />
        </span>
      </p>

      <div className="aud-view">
        <Segmented
          value={view}
          onChange={(v: View) => update({ view: v === "all" ? "" : v, page: "" })}
          ariaLabel="View"
          options={[
            { value: "all", label: <Bi en="Everything" ar="كل السجلات" /> },
            { value: "decisions", label: <Bi en="Decisions and actions" ar="القرارات والإجراءات" /> },
          ]}
        />
        {view === "decisions" && (
          <span className="aud-view-note">
            <Bi en="Routine pipeline rows (per-clause actions, priorities, impact, webhooks) are hidden here." ar="أُخفيت هنا السجلات الروتينية للمسار (إجراءات البنود والأولويات والأثر وإشعارات الويب)." />
          </span>
        )}
      </div>

      <Card className="aud-filters" headless>
        <div className="aud-filter-grid">
          <Field label={<Bi en="Event" ar="الحدث" />} htmlFor="aud-event">
            <Select id="aud-event" value={event} onChange={(e) => setFilter("event", e.target.value)}>
              <option value="">{pick(lang, "All events", "كل الأحداث")}</option>
              {(events.data ?? []).map((e) => (
                <option key={e.event} value={e.event}>{`${pick(lang, e.label_en, e.label_ar)} (${e.count})`}</option>
              ))}
              {event && !(events.data ?? []).some((e) => e.event === event) && <option value={event}>{event}</option>}
            </Select>
          </Field>
          <Field label={<Bi en="Actor" ar="المنفِّذ" />} htmlFor="aud-actor">
            <Select id="aud-actor" value={actor} onChange={(e) => setFilter("actor", e.target.value)}>
              <option value="">{pick(lang, "All actors", "كل المنفِّذين")}</option>
              {actorOptions.map((a) => (
                <option key={a.actor} value={a.actor}>{a.count ? `${a.actor} (${a.count})` : a.actor}</option>
              ))}
            </Select>
          </Field>
          <Field label={<Bi en="From date" ar="من تاريخ" />} htmlFor="aud-since">
            <Input id="aud-since" type="date" value={since} onChange={(e) => setFilter("since", e.target.value)} />
          </Field>
          <div className="aud-filter-reset">
            <Button variant="ghost" size="sm" icon={<Icon icon={RotateCcw} size={14} />} disabled={!filtered} onClick={() => update({ event: "", actor: "", since: "", view: "", page: "" })}>
              <Bi en="Reset filters" ar="إعادة ضبط الفلاتر" />
            </Button>
          </div>
        </div>
      </Card>

      {audit.loading ? (
        <Card><BrandMotif variant="spinner" title={<Bi en="Loading the audit log" ar="جارٍ تحميل سجل التدقيق" />} /></Card>
      ) : missing ? (
        <Card><BrandMotif title={<Bi en="The audit log is not available" ar="سجل التدقيق غير متاح" />} hint={<Bi en="The backend does not serve /audit yet." ar="الخادم لا يوفّر مسار سجل التدقيق بعد." />} /></Card>
      ) : !page ? (
        <Card><BrandMotif title={<Bi en="Could not load the audit log" ar="تعذّر تحميل سجل التدقيق" />} hint={<Bi en="The backend did not answer. The page retries automatically." ar="لم يستجب الخادم. ستُعاد المحاولة تلقائيًا." />} /></Card>
      ) : page.items.length === 0 ? (
        <Card>
          <BrandMotif
            title={filtered ? <Bi en="No entries match these filters" ar="لا توجد سجلات تطابق هذه الفلاتر" /> : <Bi en="The audit log is empty" ar="سجل التدقيق فارغ" />}
            hint={filtered ? <Bi en="Reset the filters to see every entry." ar="أعد ضبط الفلاتر لعرض كل السجلات." /> : <Bi en="Entries appear as the agent runs and people make decisions." ar="تظهر السجلات عندما يعمل الوكيل ويتخذ المستخدمون قراراتهم." />}
          />
        </Card>
      ) : (
        <div className={`aud-table${fresh ? "" : " is-stale"}`}>
          <DataTable caption={<Bi en="Audit log entries" ar="سجلات التدقيق" />}>
            <thead>
              <tr>
                <th><span className="sr-only"><Bi en="Details" ar="التفاصيل" /></span></th>
                <th><Bi en="When" ar="التوقيت" /></th>
                <th><Bi en="Actor" ar="المنفِّذ" /></th>
                <th><Bi en="Event" ar="الحدث" /></th>
                <th><Bi en="What happened" ar="ما الذي حدث" /></th>
                <th><Bi en="Reference" ar="المرجع" /></th>
              </tr>
            </thead>
            <tbody>
              {page.items.map((row) => (
                <AuditTableRow key={row.id} row={row} label={labelOf.get(row.event) ?? null} open={openIds.has(row.id)} onToggle={() => toggle(row.id)} />
              ))}
            </tbody>
          </DataTable>

          <nav className="aud-pager" aria-label="Pagination">
            <span className="aud-range" aria-live="polite">
              <Bi en={`${from}-${to} of ${total}`} ar={`${from}-${to} من ${total}`} />
            </span>
            <div className="aud-pager-btns">
              <Button variant="secondary" size="sm" disabled={pageNo <= 1} onClick={() => update({ page: String(pageNo - 1) })} icon={<Icon icon={ChevronLeft} size={16} flipRtl />}>
                <Bi en="Previous" ar="السابق" />
              </Button>
              <span className="aud-page tabular"><Bi en={`Page ${pageNo} of ${lastPage}`} ar={`صفحة ${pageNo} من ${lastPage}`} /></span>
              <Button variant="secondary" size="sm" disabled={pageNo >= lastPage} onClick={() => update({ page: String(pageNo + 1) })}>
                <Bi en="Next" ar="التالي" />
                <Icon icon={ChevronRight} size={16} flipRtl />
              </Button>
            </div>
          </nav>
        </div>
      )}
    </main>
  );
}

export default function AuditPage() {
  return (
    <Suspense fallback={<main><BrandMotif variant="spinner" title={<Bi en="Loading the audit log" ar="جارٍ تحميل سجل التدقيق" />} /></main>}>
      <AuditView />
    </Suspense>
  );
}
