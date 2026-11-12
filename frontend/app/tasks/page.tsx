"use client";

import Link from "next/link";
import { Suspense, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ExternalLink, FilePen, ListChecks, RefreshCw, Timer, TriangleAlert, User } from "lucide-react";
import { Bi } from "@/components/Bi";
import { RelTime } from "@/components/RelTime";
import {
  Badge, BrandMotif, Button, Card, DataTable, Icon, Input, PageHeader, PriorityPill, Segmented, StatCard, actionStatusVariant, useToast,
} from "@/components/ui";
import type { BadgeVariant, Priority } from "@/components/ui";
import { ApiError, getErpStatus, getTasks, syncErp } from "@/lib/api-visibility";
import { t as pick, useLang } from "@/lib/lang";
import { absoluteDate, dueText } from "@/lib/time";
import { usePoll } from "@/lib/use-poll";
import type { TaskItem, TasksPage } from "@/lib/types-visibility";
import { getStoredWhoAmI, setStoredWhoAmI } from "@/lib/whoami";

type Filter = "all" | "open" | "waiting" | "done" | "overdue" | "mine";
const FILTERS: Filter[] = ["all", "open", "waiting", "done", "overdue", "mine"];
const PAGE = 100;

/** Server-side query for each tab; overdue and mine are refined on the client. */
function queryFor(filter: Filter): { status?: string; assigned?: boolean } {
  switch (filter) {
    case "open": return { status: "unresolved" };
    case "waiting": return { status: "open" };
    case "done": return { status: "done,approved" };
    case "overdue": return { status: "unresolved" };
    case "mine": return { assigned: true };
    default: return {};
  }
}

const STATUS_BADGE_OVERRIDE: Record<string, BadgeVariant> = { dismissed: "neutral" };

function erpStageVariant(stage: string | null | undefined): BadgeVariant {
  const s = (stage ?? "").toLowerCase();
  if (/(done|complete|closed|resolved|finished)/.test(s)) return "approved";
  if (/(progress|review|waiting|blocked|pending|hold)/.test(s)) return "pending";
  if (/(new|todo|to do|draft|backlog|open)/.test(s)) return "new";
  return "neutral";
}

const PRIORITY_KEY_TO_PILL: Record<string, Priority> = { critical: "critical", quick: "quick", strategic: "strategic", followup: "followup" };

function fileName(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).pop() ?? path;
}

function DueCell({ t }: { t: TaskItem }) {
  const lang = useLang();
  const unresolved = t.status === "pending" || t.status === "awaiting_confirmation";
  if (!t.due_date) {
    return <span className="tsk-muted"><Bi en="No due date" ar="بلا موعد محدد" /></span>;
  }
  const rel = unresolved ? dueText(t.days_left) : null;
  return (
    <div className={`tsk-due${t.is_overdue ? " is-overdue" : ""}`}>
      <span className="tsk-due-date">
        {t.is_overdue && <Icon icon={TriangleAlert} size={13} />}
        <bdi>{absoluteDate(t.due_date, lang)}</bdi>
      </span>
      {rel && <span className="tsk-due-rel"><Bi en={rel.en} ar={rel.ar} /></span>}
    </div>
  );
}

function ErpCell({ t }: { t: TaskItem }) {
  const erp = t.erp;
  if (!erp || !erp.system) return <span className="tsk-muted">-</span>;
  const name = erp.system.toLowerCase() === "odoo" ? "Odoo" : erp.system;
  return (
    <div className="tsk-erp">
      <div className="tsk-erp-head">
        <b><bdi>{name}</bdi></b>
        {erp.stage ? <Badge variant={erpStageVariant(erp.stage)}><bdi>{erp.stage}</bdi></Badge> : null}
      </div>
      <span className="tsk-sync">
        <Bi en="Last synced " ar="آخر مزامنة " />
        <RelTime iso={erp.synced_at ?? null} never={<Bi en="not yet" ar="لم تتم بعد" />} />
      </span>
      {erp.url && (
        <a className="tsk-erp-link" href={erp.url} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()}>
          <Bi en={`Open in ${name}`} ar={`فتح في ${name}`} />
          <Icon icon={ExternalLink} size={13} />
        </a>
      )}
    </div>
  );
}

function TaskRow({ t, onOpen }: { t: TaskItem; onOpen: () => void }) {
  const effect = t.effect && t.effect.path ? t.effect : null;
  const badge = STATUS_BADGE_OVERRIDE[t.status] ?? actionStatusVariant(t.status);
  return (
    <tr className={`is-clickable${t.is_overdue ? " tsk-overdue" : ""}`} onClick={onOpen}>
      <td className="tsk-cell-task">
        <Link href={`/changes/${t.change_id}`} className="tsk-title" onClick={(e) => e.stopPropagation()}>
          <Bi en={t.action_type_label_en} ar={t.action_type_label_ar} />
        </Link>
        <span className="tsk-sub"><Bi en={t.change_title_en} ar={t.change_title_ar} /></span>
        <span className="tsk-meta">
          {t.clause_ref && <bdi className="mono">{t.clause_ref}</bdi>}
          {t.impact_node_name && <bdi>{t.impact_node_name}</bdi>}
        </span>
        {effect && (
          <Link href={`/changes/${t.change_id}`} className="tsk-effect" onClick={(e) => e.stopPropagation()} title={effect.path}>
            <Icon icon={FilePen} size={13} />
            <span>
              <Bi
                en={<>Agent edited <bdi className="mono">{fileName(effect.path ?? "")}</bdi></>}
                ar={<>عدّل الوكيل الملف <bdi className="mono">{fileName(effect.path ?? "")}</bdi></>}
              />
              {" "}
              <bdi dir="ltr" className="tsk-diffstat">(<span className="add">+{effect.added ?? 0}</span> <span className="del">-{effect.removed ?? 0}</span>)</bdi>
            </span>
          </Link>
        )}
      </td>
      <td>{t.priority_key ? <PriorityPill priority={PRIORITY_KEY_TO_PILL[t.priority_key]} /> : <span className="tsk-muted">-</span>}</td>
      <td><Badge variant={badge}><Bi en={t.status_label_en} ar={t.status_label_ar} /></Badge></td>
      <td><DueCell t={t} /></td>
      <td>
        {t.assignee_name ? (
          <div className="tsk-assignee">
            <span><Icon icon={User} size={13} /><bdi>{t.assignee_name}</bdi></span>
            {t.owner_node_name && <small><bdi>{t.owner_node_name}</bdi></small>}
          </div>
        ) : (
          <span className="tsk-muted">
            <Bi en="Unassigned" ar="غير مُسنَدة" />
            {t.owner_node_name && <small className="tsk-owner"><bdi>{t.owner_node_name}</bdi></small>}
          </span>
        )}
      </td>
      <td><ErpCell t={t} /></td>
    </tr>
  );
}

function TasksView() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const toast = useToast();
  const lang = useLang();
  const raw = params.get("filter");
  const filter: Filter = FILTERS.includes(raw as Filter) ? (raw as Filter) : "all";
  const [limit, setLimit] = useState(PAGE);
  const [whoAmI, setWhoAmI] = useState("");
  const [syncing, setSyncing] = useState(false);

  useEffect(() => setWhoAmI(getStoredWhoAmI()), []);

  function setFilter(next: Filter) {
    setLimit(PAGE);
    const sp = new URLSearchParams(params.toString());
    if (next === "all") sp.delete("filter");
    else sp.set("filter", next);
    const qs = sp.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }

  const key = `${filter}:${limit}`;
  const tasks = usePoll<{ key: string; page: TasksPage }>(
    (signal) => getTasks({ ...queryFor(filter), limit }, signal).then((page) => ({ key, page })),
    20_000,
    [key],
  );
  const erp = usePoll(getErpStatus, 60_000);
  const erpMissing = erp.error instanceof ApiError && erp.error.status === 404;
  const erpDown = !!erp.data && !erp.data.reachable;

  const fresh = tasks.data?.key === key;
  const page = tasks.data?.page ?? null;
  const summary = page?.summary ?? null;

  const rows = useMemo(() => {
    if (!page) return [];
    let items = page.items;
    if (filter === "overdue") items = items.filter((t) => t.is_overdue);
    if (filter === "mine") {
      const me = whoAmI.trim().toLowerCase();
      items = me ? items.filter((t) => (t.assignee_name ?? "").toLowerCase().includes(me)) : items;
    }
    return items;
  }, [page, filter, whoAmI]);

  async function runSync() {
    setSyncing(true);
    try {
      const res = await syncErp();
      const checked = typeof res.checked === "number" ? res.checked : null;
      toast.success(
        <Bi
          en={checked == null ? "ERP status refreshed." : `ERP status refreshed: ${checked} ${checked === 1 ? "task" : "tasks"} checked.`}
          ar={checked == null ? "تم تحديث حالة نظام تخطيط الموارد." : `تم تحديث حالة نظام تخطيط الموارد: جرى فحص ${checked} مهمة.`}
        />,
      );
      tasks.reload();
      erp.reload();
    } catch (err) {
      const e = err instanceof ApiError ? err : null;
      toast.error(
        <Bi
          en={e?.messageEn ?? "The ERP sync failed. The last known status is still shown."}
          ar={e?.messageAr ?? "تعذّرت مزامنة نظام تخطيط الموارد. ما زالت آخر حالة معروفة معروضة."}
        />,
      );
    } finally {
      setSyncing(false);
    }
  }

  const missing = !page && tasks.error instanceof ApiError && tasks.error.status === 404;
  const options: { value: Filter; label: React.ReactNode }[] = [
    { value: "all", label: <Bi en="All" ar="الكل" /> },
    { value: "open", label: <Bi en="Open" ar="مفتوحة" /> },
    { value: "waiting", label: <Bi en="Waiting for confirmation" ar="بانتظار التأكيد" /> },
    { value: "done", label: <Bi en="Done" ar="منجزة" /> },
    { value: "overdue", label: <Bi en="Overdue" ar="متأخرة" /> },
    { value: "mine", label: <Bi en="Assigned to me" ar="المُسنَدة إليّ" /> },
  ];
  // overdue and mine are refined on the client, so their total is the number of rows we hold
  const shownTotal = page && (filter === "overdue" || filter === "mine") ? rows.length : page?.total ?? 0;
  const doneCount = summary ? (summary.by_status.done ?? 0) + (summary.by_status.approved ?? 0) : null;
  const dash = "-";

  return (
    <main className="tsk">
      <PageHeader
        title={<Bi en="Tasks" ar="المهام" />}
        subtitle={<Bi en="Every action the agent proposed, who owns it, and where it stands, including tasks escalated to the ERP." ar="كل إجراء اقترحه الوكيل، ومن يتولاه، وأين وصل، بما في ذلك المهام المُصعَّدة إلى نظام تخطيط الموارد." />}
        actions={
          !erpMissing ? (
            <Button
              variant="secondary"
              icon={<Icon icon={RefreshCw} size={16} />}
              loading={syncing}
              disabled={erpDown}
              onClick={runSync}
              title={erpDown ? pick(lang, "Odoo is not reachable", "نظام Odoo غير متاح حاليًا") : undefined}
            >
              <Bi en="Sync now" ar="مزامنة الآن" />
            </Button>
          ) : undefined
        }
      />

      {erpDown && erp.data && (
        <p className="tsk-note" role="status">
          <Icon icon={TriangleAlert} size={14} />
          <span>
            <Bi en={erp.data.message_en} ar={erp.data.message_ar} />{" "}
            <Bi en="The ERP column shows the last known status." ar="يعرض عمود نظام تخطيط الموارد آخر حالة معروفة." />
          </span>
        </p>
      )}

      <div className="tsk-stats">
        <StatCard label={<Bi en="Open tasks" ar="مهام مفتوحة" />} value={summary ? summary.open : dash} trend={<Bi en="Waiting for confirmation" ar="بانتظار التأكيد" />} icon={<Icon icon={ListChecks} size={16} />} />
        <StatCard tone={summary && summary.overdue > 0 ? "critical" : "default"} label={<Bi en="Overdue" ar="متأخرة" />} value={summary ? summary.overdue : dash} trend={<Bi en="Past the internal due date" ar="تجاوزت الموعد الداخلي" />} icon={<Icon icon={Timer} size={16} />} />
        <StatCard tone={summary && summary.due_within_5_days > 0 ? "warning" : "default"} label={<Bi en="Due in 5 days" ar="تستحق خلال 5 أيام" />} value={summary ? summary.due_within_5_days : dash} trend={<Bi en="Open tasks only" ar="من المهام المفتوحة" />} />
        <StatCard label={<Bi en="Pending review" ar="بانتظار القرار" />} value={summary ? summary.pending_review : dash} trend={<Bi en="No decision yet" ar="لم يُتخذ قرار بعد" />} />
        <StatCard tone={doneCount ? "success" : "default"} label={<Bi en="Done or approved" ar="منجزة أو معتمدة" />} value={doneCount ?? dash} trend={<Bi en="Resolved actions" ar="إجراءات جرت معالجتها" />} />
      </div>

      <div className="tsk-toolbar">
        <Segmented value={filter} onChange={setFilter} options={options} ariaLabel="Filter tasks" />
        <div className="tsk-toolbar-end" aria-live="polite">
          {page && (
            <span className="tsk-count">
              <Bi en={`Showing ${rows.length} of ${shownTotal}`} ar={`عرض ${rows.length} من ${shownTotal}`} />
            </span>
          )}
          {tasks.updatedAt && (
            <span className="tsk-updated">
              <Bi en="Updated " ar="حُدّثت " />
              <RelTime iso={new Date(tasks.updatedAt).toISOString()} />
            </span>
          )}
        </div>
      </div>

      {filter === "mine" && (
        <div className="tsk-whoami">
          <label htmlFor="tsk-me" className="xp-label"><Bi en="Your name (kept in this browser only)" ar="اسمك (يُحفظ في هذا المتصفح فقط)" /></label>
          <Input
            id="tsk-me"
            value={whoAmI}
            onChange={(e) => {
              setWhoAmI(e.target.value);
              setStoredWhoAmI(e.target.value);
            }}
            placeholder="..."
          />
        </div>
      )}

      {tasks.error != null && page && (
        <p className="tsk-note" role="status">
          <Icon icon={TriangleAlert} size={14} />
          <span>
            <Bi en="Could not refresh. Showing the last update, " ar="تعذّر التحديث. المعروض هو آخر تحديث، " />
            <RelTime iso={tasks.updatedAt ? new Date(tasks.updatedAt).toISOString() : null} />
          </span>
        </p>
      )}

      {tasks.loading ? (
        <Card><BrandMotif variant="spinner" title={<Bi en="Loading tasks" ar="جارٍ تحميل المهام" />} /></Card>
      ) : missing ? (
        <Card>
          <BrandMotif title={<Bi en="Tasks are not available" ar="المهام غير متاحة" />} hint={<Bi en="The backend does not serve /tasks yet." ar="الخادم لا يوفّر مسار المهام بعد." />} />
        </Card>
      ) : !page ? (
        <Card>
          <BrandMotif title={<Bi en="Could not load tasks" ar="تعذّر تحميل المهام" />} hint={<Bi en="The backend did not answer. The page retries automatically." ar="لم يستجب الخادم. ستُعاد المحاولة تلقائيًا." />} />
        </Card>
      ) : rows.length === 0 ? (
        <Card>
          <BrandMotif
            title={filter === "all" ? <Bi en="No tasks yet" ar="لا توجد مهام بعد" /> : <Bi en="Nothing matches this filter" ar="لا يوجد ما يطابق هذا الفلتر" />}
            hint={
              filter === "mine" && !whoAmI.trim()
                ? <Bi en="Enter your name above to see the tasks assigned to you." ar="أدخل اسمك أعلاه لعرض المهام المُسنَدة إليك." />
                : <Bi en="Actions appear here once the agent finds changes. Delegate one to an owner or through the ERP from a change page." ar="تظهر الإجراءات هنا عندما يرصد الوكيل تغييرات. أسنِد أحدها إلى مسؤول أو عبر نظام تخطيط الموارد من صفحة التغيير." />
            }
          />
        </Card>
      ) : (
        <div className={`tsk-table${fresh ? "" : " is-stale"}`}>
          <DataTable caption={<Bi en="Tasks" ar="المهام" />}>
            <thead>
              <tr>
                <th><Bi en="Task" ar="المهمة" /></th>
                <th><Bi en="Priority" ar="الأولوية" /></th>
                <th><Bi en="Status" ar="الحالة" /></th>
                <th><Bi en="Due" ar="الموعد" /></th>
                <th><Bi en="Assignee" ar="المسؤول" /></th>
                <th><Bi en="ERP" ar="نظام تخطيط الموارد" /></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((t) => (
                <TaskRow key={t.id} t={t} onOpen={() => router.push(`/changes/${t.change_id}`)} />
              ))}
            </tbody>
          </DataTable>
          {page.items.length < page.total && (
            <div className="tsk-more">
              <Button variant="secondary" size="sm" onClick={() => setLimit((n) => n + PAGE)}>
                <Bi en="Show more" ar="عرض المزيد" />
              </Button>
            </div>
          )}
        </div>
      )}
    </main>
  );
}

export default function TasksPage() {
  return (
    <Suspense fallback={<main><BrandMotif variant="spinner" title={<Bi en="Loading tasks" ar="جارٍ تحميل المهام" />} /></main>}>
      <TasksView />
    </Suspense>
  );
}
