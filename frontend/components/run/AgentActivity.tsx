"use client";

import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import {
  Activity, CheckCheck, CircleCheck, CircleX, ClipboardCheck, Download, FilePen, GitCompare, Gauge, Hourglass, Info, Layers,
  ListChecks, Network, Pause, PlugZap, Radar, RefreshCw, RotateCcw, ScanSearch, Send, Tags, Undo2, UserRoundCheck,
} from "lucide-react";
import { Bi } from "@/components/Bi";
import { RelTime } from "@/components/RelTime";
import { BrandMotif, Card, Icon } from "@/components/ui";
import type { ActivityItem } from "@/lib/types-demo";

const ICONS: Record<string, LucideIcon> = {
  activity: Activity, "check-check": CheckCheck, "circle-check": CircleCheck, "circle-x": CircleX, "clipboard-check": ClipboardCheck,
  download: Download, "file-pen": FilePen, "git-compare": GitCompare, gauge: Gauge, hourglass: Hourglass, layers: Layers,
  "list-checks": ListChecks, network: Network, pause: Pause, "plug-zap": PlugZap, radar: Radar, "refresh-cw": RefreshCw,
  "rotate-ccw": RotateCcw, "scan-search": ScanSearch, send: Send, tags: Tags, "undo-2": Undo2, "user-round-check": UserRoundCheck,
};

export const ACTIVITY_LIMIT = 8;

/**
 * Compact "Agent activity": the last events from the audit log in plain
 * language, newest first, each with its time. The tone (info, success,
 * warning, danger) is shown by icon and colour together.
 */
export function AgentActivity({
  items, loading, unavailable, source, footer,
}: {
  items: ActivityItem[] | null;
  loading: boolean;
  unavailable: boolean;
  /** "audit" (real feed) or "stages" (derived from the current run when the feed is missing). */
  source: "audit" | "stages";
  footer?: ReactNode;
}) {
  const rows = (items ?? []).slice(0, ACTIVITY_LIMIT);
  return (
    <Card title={<Bi en="Agent activity" ar="نشاط الوكيل" />} icon={<Icon icon={Activity} size={18} />} className="run-activity" pad={false}>
      <div className="run-activity-body">
        {loading && !items ? (
          <BrandMotif variant="spinner" compact title={<Bi en="Loading" ar="جارٍ التحميل" />} />
        ) : unavailable && rows.length === 0 ? (
          <BrandMotif variant="empty" compact title={<Bi en="The activity feed is not available" ar="سجل النشاط غير متاح" />} hint={<Bi en="The backend does not answer this request." ar="الخادم لا يستجيب لهذا الطلب." />} />
        ) : rows.length === 0 ? (
          <BrandMotif variant="empty" compact title={<Bi en="No activity yet" ar="لا يوجد نشاط بعد" />} hint={<Bi en="Events appear here as soon as the agent does something." ar="تظهر الأحداث هنا فور أن ينفذ الوكيل أي عملية." />} />
        ) : (
          <ul className="run-activity-list">
            {rows.map((it) => {
              const Glyph = ICONS[it.icon] ?? Info;
              return (
                <li key={it.id} className={`run-act is-${it.severity}`}>
                  <span className="run-act-icon" aria-hidden="true"><Icon icon={Glyph} size={15} /></span>
                  <div className="run-act-main">
                    <p className="run-act-text"><Bi en={it.text_en} ar={it.text_ar} /></p>
                  </div>
                  <RelTime iso={it.ts} className="run-act-time" />
                </li>
              );
            })}
          </ul>
        )}
      </div>
      <p className="run-activity-foot">
        {source === "stages"
          ? <Bi en="Built from the pipeline steps (the audit feed is not available)." ar="مبنيّ على خطوات المعالجة (سجل التدقيق غير متاح)." />
          : <Bi en="From the audit log. Nothing here is estimated." ar="من سجل التدقيق. لا شيء هنا تقديري." />}
        {footer}
      </p>
    </Card>
  );
}
