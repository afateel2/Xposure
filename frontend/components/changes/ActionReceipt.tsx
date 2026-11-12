"use client";

import { ArrowRight, ExternalLink, FilePen, History, Undo2 } from "lucide-react";
import { Bi } from "@/components/Bi";
import { Badge, Button, Icon } from "@/components/ui";
import { absoluteTime, parseTs } from "@/lib/time";
import { t, useLang } from "@/lib/lang";
import type { ActionEffect } from "@/lib/types-shared";
import { DiffViewer } from "./DiffViewer";
import { RelTime } from "./RelTime";

/**
 * The receipt of a real agent action: which company file was edited, the
 * version step, +added/-removed counters, the unified diff, when it ran, a
 * link to the file in the Facility profile and an Undo. Everything shown is
 * read from the executor's `effect`; nothing is described by the model.
 */
export function ActionReceipt({
  effect, undoBusy, onUndo,
}: {
  effect: ActionEffect;
  undoBusy: boolean;
  onUndo: () => void;
}) {
  const lang = useLang();
  const fileHref = `/company?file=${encodeURIComponent(effect.path)}`;
  const executed = parseTs(effect.executed_at) != null ? effect.executed_at : null;
  return (
    <section className="eff-receipt" aria-label={t(lang, "Action receipt: the agent edited a file", "إيصال الإجراء: عدّل الوكيل ملفًا")}>
      <header className="eff-head">
        <span className="eff-icon" aria-hidden="true"><Icon icon={FilePen} size={22} /></span>
        <div className="eff-head-text">
          <div className="eff-kicker"><Bi en="Action receipt" ar="إيصال الإجراء" /></div>
          <h4 className="eff-title">
            <Bi
              en={<>The agent edited <bdi className="eff-path mono">{effect.path}</bdi></>}
              ar={<>عدّل الوكيل الملف <bdi className="eff-path mono">{effect.path}</bdi></>}
            />
          </h4>
        </div>
        <div className="eff-counters" aria-label={t(lang, `${effect.added} lines added, ${effect.removed} lines removed`, `أُضيف ${effect.added} سطر وحُذف ${effect.removed} سطر`)}>
          <span className="eff-counter is-add tabular">+{effect.added}</span>
          <span className="eff-counter is-del tabular">{"−"}{effect.removed}</span>
        </div>
      </header>

      <dl className="eff-facts">
        <div>
          <dt><Bi en="Version" ar="الإصدار" /></dt>
          <dd className="mono tabular" dir="ltr">
            v{effect.version_before}
            <Icon icon={ArrowRight} size={14} />
            v{effect.version_after}
          </dd>
        </div>
        <div>
          <dt><Bi en="Executed" ar="وقت التنفيذ" /></dt>
          <dd>
            {executed ? (
              <>
                <RelTime value={executed} />
                <span className="chg-abs tabular"> ({absoluteTime(executed, lang)})</span>
              </>
            ) : (
              <Bi en="Time not recorded" ar="لم يُسجَّل الوقت" />
            )}
          </dd>
        </div>
        {effect.cached && (
          <div>
            <dt><Bi en="Source" ar="المصدر" /></dt>
            <dd>
              <Badge variant="neutral">
                <Icon icon={History} size={13} />
                <Bi en="Cached result of an earlier identical run" ar="نتيجة محفوظة من تشغيل سابق مطابق" />
              </Badge>
            </dd>
          </div>
        )}
      </dl>

      <DiffViewer diff={effect.diff_unified} />

      <footer className="eff-foot">
        <Button href={fileHref} variant="link" size="sm" icon={<Icon icon={ExternalLink} size={14} />}>
          <Bi en="View the file in Facility profile" ar="عرض الملف في ملف المنشأة" />
        </Button>
        <Button variant="secondary" size="sm" icon={<Icon icon={Undo2} size={15} flipRtl />} loading={undoBusy} onClick={onUndo}>
          <Bi en="Undo the edit" ar="التراجع عن التعديل" />
        </Button>
      </footer>
    </section>
  );
}
