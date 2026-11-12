"use client";

import type { ReactNode } from "react";
import { Bi } from "@/components/Bi";
import { RelTime } from "@/components/RelTime";
import { Badge, Button, Card, Icon, RefreshCw, Check, CircleX, LoaderCircle, TriangleAlert } from "@/components/ui";
import { Activity, Circle, Database } from "lucide-react";
import { FALLBACK_STAGES, type DemoRun, type DemoStage, type RunStatus } from "@/lib/types-demo";
import { clock, durationText, elapsedMs, fmtInt, kb, num } from "./format";

interface ChipSpec {
  key: string;
  en: string;
  ar: string;
  /** Show "value of total" using this other counter (for example classified of to_classify). */
  of?: string;
  bytes?: boolean;
}

/** The figures worth showing per stage. Keys are the backend's stage counts (backend/app/demo/runner.py). */
const CHIPS: Record<string, ChipSpec[]> = {
  portal: [
    { key: "documents_on_portal", en: "On the portal", ar: "على البوابة" },
    { key: "already_known", en: "Already known", ar: "معروفة سابقًا" },
    { key: "new_documents", en: "New", ar: "جديدة" },
  ],
  fetch: [
    { key: "files_fetched", en: "Files fetched", ar: "ملفات مجلوبة" },
    { key: "bytes", en: "Size", ar: "الحجم", bytes: true },
  ],
  ingest: [{ key: "clauses_ingested", en: "Clauses ingested", ar: "بنود مُدخلة" }],
  align: [
    { key: "exact_id", en: "Exact matches", ar: "تطابق بالرقم" },
    { key: "new", en: "New", ar: "جديدة" },
    { key: "withdrawn", en: "Withdrawn", ar: "ملغاة" },
    { key: "to_classify", en: "To classify", ar: "للتصنيف" },
  ],
  classify: [
    { key: "changes_classified", en: "Classified", ar: "مُصنّفة", of: "to_classify" },
    { key: "material_changes", en: "Material", ar: "جوهرية" },
  ],
  impact: [
    { key: "changes_traced", en: "Traced", ar: "مُتتبَّعة", of: "material_changes" },
    { key: "impacted_nodes", en: "Impacted nodes", ar: "عناصر متأثرة" },
  ],
  prioritize: [{ key: "changes_scored", en: "Changes scored", ar: "تغييرات مقيَّمة" }],
  policy: [{ key: "actions_created", en: "Actions created", ar: "إجراءات مُنشأة" }],
  auto_execute: [{ key: "auto_executed", en: "Auto-executed", ar: "نُفّذت تلقائيًا" }],
  review: [{ key: "awaiting_review", en: "Awaiting your review", ar: "بانتظار مراجعتك" }],
};

/** "Answered from the local cache" wording. Always visible, never hidden: it says what was cached and what was live. */
function cacheChips(counts: Record<string, unknown> | null | undefined): ReactNode[] {
  if (!counts) return [];
  const out: ReactNode[] = [];
  const calls = num(counts.llm_calls);
  const hits = num(counts.llm_cache_hits);
  if (calls != null && calls > 0 && hits != null) {
    const live = calls - hits;
    out.push(
      <span key="llm" className={`run-chip run-chip-cache${hits === 0 ? " is-live" : ""}`}>
        <Icon icon={Database} size={13} />
        {hits > 0 ? (
          <Bi
            en={<>Answered from the local cache: <b className="tabular">{fmtInt(hits)}</b> of <b className="tabular">{fmtInt(calls)}</b>{live > 0 ? <>, {fmtInt(live)} live</> : null}</>}
            ar={<>أُجيب من الذاكرة المحلية: <b className="tabular">{fmtInt(hits)}</b> من <b className="tabular">{fmtInt(calls)}</b>{live > 0 ? <>، و{fmtInt(live)} مباشرة</> : null}</>}
          />
        ) : (
          <Bi
            en={<>Answered live by the model: <b className="tabular">{fmtInt(calls)}</b></>}
            ar={<>أجاب عنها النموذج مباشرة: <b className="tabular">{fmtInt(calls)}</b></>}
          />
        )}
      </span>,
    );
  }
  const texts = num(counts.embeddings_total);
  const embHits = num(counts.embeddings_from_cache);
  if (texts != null && texts > 0 && embHits != null) {
    out.push(
      <span key="emb" className={`run-chip run-chip-cache${embHits === 0 ? " is-live" : ""}`}>
        <Icon icon={Database} size={13} />
        {embHits > 0 ? (
          <Bi
            en={<>Vectors from the local cache: <b className="tabular">{fmtInt(embHits)}</b> of <b className="tabular">{fmtInt(texts)}</b></>}
            ar={<>متجهات من الذاكرة المحلية: <b className="tabular">{fmtInt(embHits)}</b> من <b className="tabular">{fmtInt(texts)}</b></>}
          />
        ) : (
          <Bi
            en={<>Vectors computed live: <b className="tabular">{fmtInt(texts)}</b></>}
            ar={<>متجهات حُسبت مباشرة: <b className="tabular">{fmtInt(texts)}</b></>}
          />
        )}
      </span>,
    );
  }
  return out;
}

function countChips(stage: DemoStage): ReactNode[] {
  const counts = stage.counts ?? {};
  const out: ReactNode[] = [];
  for (const spec of CHIPS[stage.key] ?? []) {
    const value = num(counts[spec.key]);
    if (value == null) continue;
    const total = spec.of ? num(counts[spec.of]) : null;
    out.push(
      <span key={spec.key} className="run-chip">
        <Bi en={spec.en} ar={spec.ar} />
        <b className="tabular" dir="ltr">{spec.bytes ? kb(value) : total != null && total !== value ? `${fmtInt(value)} / ${fmtInt(total)}` : fmtInt(value)}</b>
      </span>,
    );
  }
  return [...out, ...cacheChips(counts)];
}

const STATE_LABEL: Record<DemoStage["status"], { en: string; ar: string }> = {
  pending: { en: "Waiting", ar: "بانتظار الدور" },
  running: { en: "Running", ar: "قيد التنفيذ" },
  done: { en: "Done", ar: "اكتملت" },
  failed: { en: "Failed", ar: "فشلت" },
};

function Marker({ status }: { status: DemoStage["status"] }) {
  return (
    <span className="run-marker" aria-hidden="true">
      {status === "running" ? <Icon icon={LoaderCircle} size={16} className="run-spin" />
        : status === "done" ? <Icon icon={Check} size={16} />
          : status === "failed" ? <Icon icon={CircleX} size={16} />
            : <Icon icon={Circle} size={10} />}
    </span>
  );
}

export function RunStatusBadge({ status }: { status: RunStatus }) {
  switch (status) {
    case "running":
      return <Badge variant="new"><Icon icon={LoaderCircle} size={13} className="run-spin" /><Bi en="Running" ar="قيد التنفيذ" /></Badge>;
    case "awaiting_review":
      return <Badge variant="pending"><Bi en="Awaiting your review" ar="بانتظار مراجعتك" /></Badge>;
    case "completed":
      return <Badge variant="approved"><Bi en="Completed" ar="اكتمل" /></Badge>;
    case "failed":
      return <Badge variant="rejected"><Bi en="Failed" ar="فشل" /></Badge>;
    default:
      return <Badge variant="neutral"><Bi en="Idle" ar="خامل" /></Badge>;
  }
}

/**
 * The live pipeline: one row per stage with a state marker (spinner, check,
 * cross, ring), the stage's own sentence from the backend, key figures, the
 * local cache disclosure and an elapsed timer. Every stage is always
 * rendered (pending ones compact), so nothing jumps while polling.
 */
export function PipelineStepper({
  run, now, onRetry, retrying, unavailable,
}: {
  run: DemoRun | null;
  now: number;
  onRetry: () => void;
  retrying: boolean;
  unavailable: boolean;
}) {
  const status: RunStatus = run?.status ?? "idle";
  const stages = run && run.stages.length > 0 ? run.stages : FALLBACK_STAGES;
  const total = stages.length;
  const doneCount = stages.filter((s) => s.status === "done").length;
  const active = stages.find((s) => s.status === "running") ?? stages.find((s) => s.status === "failed") ?? null;
  const activeIndex = active ? stages.indexOf(active) + 1 : doneCount;
  const failedStage = stages.find((s) => s.status === "failed") ?? null;
  const totalMs = run ? elapsedMs(run.started_at, run.finished_at, now) : null;
  const showFooterNote = status !== "idle" && (run?.note_en || run?.note_ar);

  const liveLine: BiLine | null = active
    ? { en: `Step ${activeIndex} of ${total}: ${active.label_en}, ${STATE_LABEL[active.status].en}`, ar: `الخطوة ${activeIndex} من ${total}: ${active.label_ar}، ${STATE_LABEL[active.status].ar}` }
    : status === "awaiting_review" || status === "completed"
      ? { en: "The scan finished.", ar: "انتهى الفحص." }
      : null;

  return (
    <Card
      title={<Bi en="Live pipeline" ar="مسار المعالجة المباشر" />}
      icon={<Icon icon={Activity} size={18} />}
      actions={<RunStatusBadge status={status} />}
      className="run-pipeline"
    >
      <div className="run-meta">
        {unavailable ? (
          <span className="run-meta-item"><Bi en="Progress is not available: the demo service does not answer." ar="تعذّر عرض التقدم: خدمة العرض لا تستجيب." /></span>
        ) : status === "idle" ? (
          <span className="run-meta-item"><Bi en="No scan has run yet. Press Scan now and the steps below fill in live." ar="لم يُجرَ أي فحص بعد. اضغط «افحص الآن» لتُملأ الخطوات أدناه مباشرة." /></span>
        ) : (
          <>
            <span className="run-meta-item">
              <span className="run-meta-label"><Bi en="Started" ar="بدأ" /></span>
              <RelTime iso={run?.started_at} />
            </span>
            <span className="run-meta-item">
              <span className="run-meta-label"><Bi en="Elapsed" ar="المدة" /></span>
              <b className="tabular mono" dir="ltr">{totalMs != null ? clock(totalMs) : "0:00"}</b>
            </span>
            <span className="run-meta-item">
              <span className="run-meta-label"><Bi en="Step" ar="الخطوة" /></span>
              <b className="tabular" dir="ltr">{Math.max(activeIndex, status === "running" ? 1 : doneCount)} / {total}</b>
            </span>
          </>
        )}
      </div>

      {failedStage && status === "failed" && (
        <div className="run-failed" role="alert">
          <Icon icon={TriangleAlert} size={18} />
          <div className="run-failed-text">
            <b><Bi en="The scan stopped and nothing was marked as done." ar="توقف الفحص ولم يُعدّ أي شيء منجزًا." /></b>
            <span>
              <Bi en={failedStage.label_en} ar={failedStage.label_ar} />
              {run?.error?.reason ? <>: <bdi dir="auto">{run.error.reason}</bdi></> : null}
            </span>
          </div>
          <Button variant="secondary" size="sm" icon={<Icon icon={RefreshCw} size={14} />} loading={retrying} onClick={onRetry}>
            <Bi en="Retry" ar="إعادة المحاولة" />
          </Button>
        </div>
      )}

      <ol className="run-steps" aria-label="Pipeline">
        {stages.map((stage, i) => {
          const ms = stage.status === "running" || stage.status === "done" || stage.status === "failed"
            ? elapsedMs(stage.started_at, stage.status === "running" ? null : stage.ended_at, now)
            : null;
          const dur = ms != null ? durationText(ms) : null;
          const chips = stage.status === "pending" ? [] : countChips(stage);
          const detailEn = stage.status === "pending" ? null : stage.detail_en;
          const detailAr = stage.status === "pending" ? null : stage.detail_ar;
          return (
            <li key={stage.key} className={`run-step is-${stage.status}`} aria-current={stage.status === "running" ? "step" : undefined}>
              <Marker status={stage.status} />
              <div className="run-step-main">
                <div className="run-step-head">
                  <span className="run-step-num tabular" aria-hidden="true">{i + 1}</span>
                  <span className="run-step-label"><Bi en={stage.label_en} ar={stage.label_ar} /></span>
                  <span className="sr-only">, <Bi en={STATE_LABEL[stage.status].en} ar={STATE_LABEL[stage.status].ar} /></span>
                </div>
                {(detailEn || detailAr) && (
                  <p className="run-step-detail"><Bi en={detailEn ?? ""} ar={detailAr ?? detailEn ?? ""} /></p>
                )}
                {chips.length > 0 && <div className="run-chips">{chips}</div>}
              </div>
              <span className="run-step-time tabular">
                {dur ? <Bi en={dur.en} ar={dur.ar} /> : null}
              </span>
            </li>
          );
        })}
      </ol>

      {showFooterNote && (
        <p className="run-footnote">
          <Icon icon={Database} size={14} />
          <span><Bi en={run?.note_en ?? ""} ar={run?.note_ar ?? run?.note_en ?? ""} /></span>
        </p>
      )}

      {/* Announces step changes and the end of the run to screen readers. */}
      <p className="sr-only" role="status" aria-live="polite">
        {liveLine ? <Bi en={liveLine.en} ar={liveLine.ar} /> : null}
      </p>
    </Card>
  );
}

interface BiLine { en: string; ar: string }
