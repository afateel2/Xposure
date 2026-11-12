"use client";

import Link from "next/link";
import { useCallback, useState } from "react";
import {
  Activity, CheckCheck, CircleCheck, CircleX, ClipboardCheck, Download, FilePen, GitCompare, Hourglass, ListChecks,
  Network, PlugZap, RefreshCw, RotateCcw, ScanSearch, Send, Tags, Undo2, UserRoundCheck,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { getActivity } from "@/lib/api-visibility";
import { usePoll } from "@/lib/use-poll";
import { ApiError } from "@/lib/api-visibility";
import type { ActivityItem, ActivityKind, Severity } from "@/lib/types-visibility";
import { Bi } from "./Bi";
import { RelTime } from "./RelTime";
import { BrandMotif } from "./ui/BrandMotif";
import { Button } from "./ui/Button";
import { Icon } from "./ui/Icon";

/** Lucide names the backend sends (kebab case) mapped to components, so the bundle stays small. */
const ICONS: Record<string, LucideIcon> = {
  "scan-search": ScanSearch, download: Download, "git-compare": GitCompare, tags: Tags, network: Network,
  "list-checks": ListChecks, send: Send, "circle-check": CircleCheck, "circle-x": CircleX, "undo-2": Undo2,
  activity: Activity, "file-pen": FilePen, hourglass: Hourglass, "check-check": CheckCheck, "plug-zap": PlugZap,
  "clipboard-check": ClipboardCheck, "user-round-check": UserRoundCheck, "rotate-ccw": RotateCcw, "refresh-cw": RefreshCw,
};

const KIND_ICON: Record<ActivityKind, LucideIcon> = {
  scan: ScanSearch, ingest: Download, diff: GitCompare, classify: Tags, impact: Network, action: ListChecks,
  delegate: Send, confirm: CircleCheck, undo: Undo2, export: Send, system: Activity, effect: FilePen,
};

const SEVERITY_LABEL: Record<Severity, { en: string; ar: string }> = {
  info: { en: "Information", ar: "معلومة" },
  success: { en: "Success", ar: "نجاح" },
  warning: { en: "Warning", ar: "تنبيه" },
  danger: { en: "Problem", ar: "مشكلة" },
};

/** Round glyph: the icon says WHAT happened, the tint says how it went (fixed status colours). */
export function ActivityGlyph({ icon, kind, severity, size = 16 }: { icon?: string; kind: ActivityKind; severity: Severity; size?: number }) {
  const Glyph = (icon && ICONS[icon]) || KIND_ICON[kind] || Activity;
  return (
    <span className={`dash-glyph sev-${severity}`}>
      <Icon icon={Glyph} size={size} />
      <span className="sr-only"><Bi en={SEVERITY_LABEL[severity].en} ar={SEVERITY_LABEL[severity].ar} />: </span>
    </span>
  );
}

function targetOf(item: ActivityItem): string | null {
  if (item.change_id) return `/changes/${item.change_id}`;
  if (item.action_id) return "/tasks";
  return null;
}

function Row({ item, compact }: { item: ActivityItem; compact: boolean }) {
  const href = targetOf(item);
  const body = (
    <>
      <ActivityGlyph icon={item.icon} kind={item.kind} severity={item.severity} />
      <span className="dash-act-main">
        <span className="dash-act-text">
          <Bi en={item.text_en} ar={item.text_ar} />
          {item.count > 1 && <bdi dir="ltr" className="dash-act-count tabular">{"×"}{item.count}</bdi>}
        </span>
        {!compact && (item.detail_en || item.detail_ar) && (
          <span className="dash-act-detail"><Bi en={item.detail_en ?? ""} ar={item.detail_ar ?? item.detail_en ?? ""} /></span>
        )}
      </span>
      <RelTime iso={item.ts} className="dash-act-time" />
    </>
  );
  return (
    <li className="dash-act-item">
      {href ? <Link href={href} className="dash-act-link">{body}</Link> : <div className="dash-act-link is-static">{body}</div>}
    </li>
  );
}

/**
 * Live activity timeline from GET /activity: plain-language events, one icon
 * per kind, severity tint, noisy repeats already collapsed by the backend
 * (shown as a x43 chip). Polls every `pollMs` while the tab is visible and
 * keeps the previous list on screen during refreshes and failures.
 *
 *   <ActivityFeed limit={12} compact />   dashboard card
 *   <ActivityFeed limit={50} />           full feed with details and "Show older"
 */
export function ActivityFeed({ limit = 20, compact = false, pollMs = 15_000 }: { limit?: number; compact?: boolean; pollMs?: number }) {
  const { data, error, loading, updatedAt } = usePoll((signal) => getActivity({ limit }, signal), pollMs, [limit]);
  const [older, setOlder] = useState<ActivityItem[]>([]);
  const [olderCursor, setOlderCursor] = useState<number | null | undefined>(undefined);
  const [loadingOlder, setLoadingOlder] = useState(false);

  const cursor = olderCursor === undefined ? data?.next_before_id ?? null : olderCursor;

  const showOlder = useCallback(async () => {
    if (cursor == null) return;
    setLoadingOlder(true);
    try {
      const page = await getActivity({ limit, beforeId: cursor });
      setOlder((cur) => [...cur, ...page.items]);
      setOlderCursor(page.next_before_id);
    } catch {
      /* keep what is on screen; the button stays available */
    } finally {
      setLoadingOlder(false);
    }
  }, [cursor, limit]);

  if (loading) return <BrandMotif variant="spinner" compact title={<Bi en="Loading activity" ar="جارٍ تحميل النشاط" />} />;

  if (!data) {
    const missing = error instanceof ApiError && error.status === 404;
    return (
      <BrandMotif
        compact
        title={<Bi en="Activity is not available" ar="تعذّر عرض النشاط" />}
        hint={missing
          ? <Bi en="The backend does not serve the activity feed yet." ar="الخادم لا يوفّر سجل النشاط بعد." />
          : <Bi en="Could not reach the backend. The feed will retry automatically." ar="تعذّر الاتصال بالخادم. ستُعاد المحاولة تلقائيًا." />}
      />
    );
  }

  const seen = new Set<number>();
  const items = [...data.items, ...older].filter((i) => (seen.has(i.id) ? false : (seen.add(i.id), true)));

  if (items.length === 0) {
    return (
      <BrandMotif
        compact
        title={<Bi en="No activity yet" ar="لا يوجد نشاط بعد" />}
        hint={<Bi en="Events appear here as the agent checks sources, compares versions and people make decisions." ar="تظهر الأحداث هنا عندما يفحص الوكيل المصادر ويقارن الإصدارات ويتخذ المستخدمون قراراتهم." />}
      />
    );
  }

  return (
    <div className={`dash-feed${compact ? " is-compact" : ""}`}>
      {error != null && (
        <p className="dash-feed-stale" role="status">
          <Bi en="Could not refresh. Showing the last update, " ar="تعذّر التحديث. المعروض هو آخر تحديث، " />
          <RelTime iso={updatedAt ? new Date(updatedAt).toISOString() : null} />
        </p>
      )}
      <ol className="dash-act-list">
        {items.map((item) => <Row key={item.id} item={item} compact={compact} />)}
      </ol>
      {!compact && cursor != null && (
        <div className="dash-feed-more">
          <Button variant="secondary" size="sm" loading={loadingOlder} onClick={showOlder}>
            <Bi en="Show older activity" ar="عرض نشاط أقدم" />
          </Button>
        </div>
      )}
    </div>
  );
}
