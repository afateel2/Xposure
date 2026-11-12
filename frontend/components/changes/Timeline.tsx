"use client";

import { useEffect, useState } from "react";
import {
  Activity, CircleCheck, CircleX, Download, FilePen, GitCompare, Hourglass, ListChecks, Network, ScanSearch, Send,
  Tags, Undo2, type LucideIcon,
} from "lucide-react";
import { Bi } from "@/components/Bi";
import { BrandMotif, Button, Icon } from "@/components/ui";
import { ApiError, errorText } from "@/lib/api-erp";
import { getChangeTimeline, type TimelineItem } from "@/lib/api-timeline";
import { absoluteTime } from "@/lib/time";
import { useLang } from "@/lib/lang";
import { actorLabel } from "./labels";
import { RelTime } from "./RelTime";

const ICONS: Record<string, LucideIcon> = {
  "scan-search": ScanSearch, download: Download, "git-compare": GitCompare, tags: Tags, network: Network,
  "list-checks": ListChecks, send: Send, "circle-check": CircleCheck, "undo-2": Undo2, activity: Activity,
  "file-pen": FilePen, hourglass: Hourglass, "circle-x": CircleX,
};
const KIND_ICON: Record<string, LucideIcon> = {
  scan: ScanSearch, ingest: Download, diff: GitCompare, classify: Tags, impact: Network, action: ListChecks,
  delegate: Send, confirm: CircleCheck, undo: Undo2, system: Activity, effect: FilePen, export: Send,
};

function iconFor(item: TimelineItem): LucideIcon {
  return (item.icon && ICONS[item.icon]) || KIND_ICON[item.kind] || Activity;
}

/**
 * Vertical lifecycle timeline of one change, from GET /changes/{id}/timeline:
 * detected, classified, impact traced, then every human and agent step. Each
 * item shows relative and absolute time. A server without the route gets an
 * honest empty state, never invented steps.
 */
export function Timeline({
  changeId, version, onOpenAction,
}: {
  changeId: number;
  /** Bump to refetch after an action changed. */
  version: number;
  onOpenAction: (actionId: number) => void;
}) {
  const lang = useLang();
  const [items, setItems] = useState<TimelineItem[] | null>(null);
  const [missing, setMissing] = useState(false);
  const [error, setError] = useState<{ en: string; ar: string } | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    getChangeTimeline(changeId)
      .then((tl) => {
        if (cancelled) return;
        setMissing(false);
        setItems(tl.items);
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setMissing(true);
        } else {
          setError(errorText(err));
        }
        setItems([]);
      });
    return () => {
      cancelled = true;
    };
  }, [changeId, version, reloadKey]);

  if (items === null) return <BrandMotif variant="spinner" compact title={<Bi en="Loading the timeline..." ar="جارٍ تحميل الخط الزمني..." />} />;

  if (error) {
    return (
      <div className="chg-tl-empty" role="alert">
        <p><Bi en={`Could not load the timeline. ${error.en}`} ar={`تعذّر تحميل الخط الزمني. ${error.ar}`} /></p>
        <Button variant="secondary" size="sm" onClick={() => setReloadKey((k) => k + 1)}><Bi en="Try again" ar="إعادة المحاولة" /></Button>
      </div>
    );
  }

  if (missing || items.length === 0) {
    return (
      <BrandMotif
        variant="empty"
        title={<Bi en="No timeline yet" ar="لا يوجد خط زمني بعد" />}
        hint={
          missing ? (
            <Bi en="This server does not provide a per-change timeline, so nothing is shown rather than guessing." ar="هذا الخادم لا يوفّر خطًا زمنيًا لكل تغيير، لذلك لا يُعرض شيء بدل التخمين." />
          ) : (
            <Bi en="Steps appear here as the agent and your team act on this change." ar="تظهر الخطوات هنا كلما تحرّك الوكيل وفريقك بشأن هذا التغيير." />
          )
        }
      />
    );
  }

  return (
    <ol className="chg-tl" aria-label={lang === "ar" ? "الخط الزمني للتغيير" : "Change timeline"}>
      {items.map((item, i) => {
        const Glyph = iconFor(item);
        const actor = actorLabel(item.actor);
        const abs = absoluteTime(item.ts, lang);
        return (
          <li key={`${item.ts}-${item.audit_id ?? i}`} className={`chg-tl-item is-${item.severity}`}>
            <span className="chg-tl-dot" aria-hidden="true"><Icon icon={Glyph} size={15} /></span>
            <div className="chg-tl-body">
              <p className="chg-tl-text"><Bi en={item.text_en} ar={item.text_ar} /></p>
              {(item.detail_en || item.detail_ar) && (
                <p className="chg-tl-detail"><Bi en={item.detail_en ?? item.detail_ar ?? ""} ar={item.detail_ar ?? item.detail_en ?? ""} /></p>
              )}
              <p className="chg-tl-meta">
                <RelTime value={item.ts} />
                <span className="chg-abs tabular">{abs}</span>
                {actor && <span className="chg-chip"><Bi en={actor.en} ar={actor.ar} /></span>}
                {item.action_id != null && (
                  <button type="button" className="chg-tl-link" onClick={() => onOpenAction(item.action_id as number)}>
                    <Bi en={`Action #${item.action_id}`} ar={`الإجراء رقم ${item.action_id}`} />
                  </button>
                )}
              </p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
