"use client";

import { CircleCheck, CircleDot, CircleHelp, ExternalLink, Hourglass, Loader, RefreshCw, Server } from "lucide-react";
import { Bi } from "@/components/Bi";
import { Badge, Button, Icon, type BadgeVariant } from "@/components/ui";
import type { ErpInfo } from "@/lib/types-shared";
import type { ErpErrorNote } from "./erp-types";
import { erpStageLabel } from "./labels";
import { RelTime } from "./RelTime";

const STAGE_STYLE: Record<string, { variant: BadgeVariant; icon: typeof CircleDot }> = {
  new: { variant: "new", icon: CircleDot },
  in_progress: { variant: "pending", icon: Loader },
  waiting: { variant: "warning", icon: Hourglass },
  done: { variant: "approved", icon: CircleCheck },
};

/**
 * The Odoo task behind a delegated action: system chip, task number, stage
 * chip (status colours: info new, warning in progress or waiting, success
 * done), assignee, honest "last synced" time with a Refresh, and a link into
 * Odoo. A failed refresh keeps the last known state and says so.
 */
export function ErpCard({
  erp, assigneeFallback, refreshing, refreshError, onRefresh,
}: {
  erp: ErpInfo;
  assigneeFallback?: string | null;
  refreshing: boolean;
  refreshError?: ErpErrorNote | null;
  onRefresh: () => void;
}) {
  const label = erpStageLabel(erp);
  const style = (erp.stage_key && STAGE_STYLE[erp.stage_key]) || { variant: "neutral" as BadgeVariant, icon: CircleHelp };
  const assignee = erp.assignee || assigneeFallback || null;
  return (
    <section className="erp-card" aria-label="Odoo task">
      <header className="erp-head">
        <span className="erp-system">
          <Icon icon={Server} size={15} />
          <span>Odoo</span>
        </span>
        <span className="erp-task mono tabular">
          <Bi en="Task" ar="مهمة" /> <bdi>#{erp.task_id}</bdi>
        </span>
        <Badge variant={style.variant} className="erp-stage">
          <Icon icon={style.icon} size={13} />
          <Bi en={label.en} ar={label.ar} />
        </Badge>
      </header>

      <dl className="erp-facts">
        <div>
          <dt><Bi en="Assignee" ar="المُكلَّف" /></dt>
          <dd>{assignee ? <bdi>{assignee}</bdi> : <span className="xp-muted"><Bi en="Not assigned" ar="غير مُسنَد" /></span>}</dd>
        </div>
        <div>
          <dt><Bi en="Last synced" ar="آخر مزامنة" /></dt>
          <dd aria-live="polite">
            {erp.synced_at ? <RelTime value={erp.synced_at} /> : <span className="xp-muted"><Bi en="Never" ar="لم تتم بعد" /></span>}
          </dd>
        </div>
      </dl>

      {refreshError && (
        <p className="erp-warn" role="alert">
          <Bi
            en={`Could not reach Odoo, so this is the last known status. ${refreshError.en}`}
            ar={`تعذّر الاتصال بنظام Odoo، لذا هذه آخر حالة معروفة. ${refreshError.ar}`}
          />
        </p>
      )}

      <footer className="erp-foot">
        <Button variant="ghost" size="sm" icon={<Icon icon={RefreshCw} size={14} />} loading={refreshing} onClick={onRefresh}>
          <Bi en="Refresh" ar="تحديث" />
        </Button>
        {erp.url && (
          <Button href={erp.url} target="_blank" rel="noopener noreferrer" variant="link" size="sm" icon={<Icon icon={ExternalLink} size={14} />}>
            <Bi en="Open in Odoo" ar="فتح في Odoo" />
          </Button>
        )}
      </footer>
    </section>
  );
}
