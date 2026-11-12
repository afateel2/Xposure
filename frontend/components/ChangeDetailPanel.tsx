"use client";

import { useCallback, useMemo, useState } from "react";
import { Download, FileSpreadsheet, FileText, GitPullRequestArrow, History, ListTree, Braces } from "lucide-react";
import { approveAction, confirmAction, dismissAction, delegateAction, getChange, undoAction } from "@/lib/api";
import { delegateToOdoo, errorText, syncErp } from "@/lib/api-erp";
import { t, useLang } from "@/lib/lang";
import { MATCH_KIND_LABEL } from "@/lib/labels";
import type { ReviewQueue } from "@/lib/review-queue";
import type { ActionOut, ActionStatus, ChangeDetailOut, ImpactOut } from "@/lib/types";
import { Bi } from "./Bi";
import { Badge, Button, Card, Icon, buttonClass, useToast } from "./ui";
import { ClauseDiff } from "./DiffQuote";
import { AssignModal, type AssignResult } from "./changes/AssignModal";
import { ImpactList, type ActionUiState } from "./changes/ImpactList";
import type { BusyKind, RevertedEffect } from "./changes/ActionCard";
import { CitationBadges } from "./changes/CitationBadges";
import type { ErpErrorNote } from "./changes/erp-types";
import { Isolated } from "./changes/Isolated";
import { effectNoteBi } from "./changes/labels";
import { PriorityBreakdown } from "./changes/PriorityBreakdown";
import { ProvenanceStrip } from "./changes/ProvenanceStrip";
import { QueueBar } from "./changes/QueueBar";
import { Tabs, panelId, tabId } from "./changes/Tabs";
import { Timeline } from "./changes/Timeline";

type TabKey = "impact" | "timeline" | "exports";

const EXPORTS: { key: "pdf" | "excel" | "oscal"; icon: typeof Download; en: string; ar: string; descEn: string; descAr: string }[] = [
  { key: "pdf", icon: FileText, en: "Export PDF", ar: "تصدير PDF", descEn: "A printable report of this change with the diff and impact.", descAr: "تقرير قابل للطباعة لهذا التغيير مع الفروقات والأثر." },
  { key: "excel", icon: FileSpreadsheet, en: "Export Excel", ar: "تصدير Excel", descEn: "A workbook with the change, impacted nodes and actions.", descAr: "مصنّف يضم التغيير والعناصر المتأثرة والإجراءات." },
  { key: "oscal", icon: Braces, en: "Export OSCAL JSON", ar: "تصدير OSCAL JSON", descEn: "Machine-readable OSCAL for GRC tools.", descAr: "صيغة OSCAL مقروءة آليًا لأدوات الحوكمة والمخاطر والامتثال." },
];

function ExportButtons({ changeId }: { changeId: number }) {
  return (
    <div className="chg-exports">
      {EXPORTS.map((e) => (
        <Card key={e.key} className="chg-export" headless>
          <div className="chg-export-body">
            <span className="chg-export-icon" aria-hidden="true"><Icon icon={e.icon} size={20} /></span>
            <p><Bi en={e.descEn} ar={e.descAr} /></p>
            <a className={buttonClass({ variant: "secondary", size: "sm" })} href={`/api/changes/${changeId}/export/${e.key}`}>
              <Icon icon={Download} size={15} />
              <Bi en={e.en} ar={e.ar} />
            </a>
          </div>
        </Card>
      ))}
    </div>
  );
}

function StatusCounts({ impacts }: { impacts: ImpactOut[] }) {
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const i of impacts) for (const a of i.actions) c[a.status] = (c[a.status] ?? 0) + 1;
    return c;
  }, [impacts]);
  const entries: { key: ActionStatus; variant: "pending" | "new" | "approved" | "neutral"; en: string; ar: string }[] = [
    { key: "pending", variant: "pending", en: "pending", ar: "قيد الانتظار" },
    { key: "awaiting_confirmation", variant: "new", en: "awaiting confirmation", ar: "بانتظار التأكيد" },
    { key: "approved", variant: "approved", en: "approved", ar: "معتمد" },
    { key: "done", variant: "approved", en: "done", ar: "منجز" },
    { key: "dismissed", variant: "neutral", en: "dismissed", ar: "مُتجاهَل" },
  ];
  const visible = entries.filter((e) => (counts[e.key] ?? 0) > 0);
  if (visible.length === 0) return null;
  return (
    <div className="chg-counts" aria-label="Actions by status">
      {visible.map((e) => (
        <Badge key={e.key} variant={e.variant}>
          <span className="tabular">{counts[e.key]}</span> <Bi en={e.en} ar={e.ar} />
        </Badge>
      ))}
    </div>
  );
}

export function ChangeDetailPanel({
  detail, mode = "full", queue,
}: {
  detail: ChangeDetailOut;
  mode?: "inline" | "full";
  /** The review queue (full page only). The bar is simply absent without it. */
  queue?: ReviewQueue;
}) {
  const lang = useLang();
  const toast = useToast();
  const [impacts, setImpacts] = useState<ImpactOut[]>(detail.impacts);
  const [tab, setTab] = useState<TabKey>("impact");
  const [timelineVersion, setTimelineVersion] = useState(0);
  const [busy, setBusy] = useState<{ id: number; kind: BusyKind } | null>(null);
  const [notes, setNotes] = useState<Record<number, { en: string; ar: string } | null>>({});
  const [reverted, setReverted] = useState<Record<number, RevertedEffect | null>>({});
  const [caveats, setCaveats] = useState<Record<number, string[]>>({});
  const [errors, setErrors] = useState<Record<number, ErpErrorNote | null>>({});
  const [erpRefreshing, setErpRefreshing] = useState<number | null>(null);
  const [erpErrors, setErpErrors] = useState<Record<number, ErpErrorNote | null>>({});
  const [assignTarget, setAssignTarget] = useState<{ action: ActionOut; impact: ImpactOut } | null>(null);

  const hasClauseText = detail.old_text_en !== null || detail.new_text_en !== null;
  const match = MATCH_KIND_LABEL[detail.match_kind] ?? { en: detail.match_kind, ar: detail.match_kind };

  const patchAction = useCallback((actionId: number, patch: Partial<ActionOut>) => {
    setImpacts((prev) =>
      prev.map((impact) => ({
        ...impact,
        actions: impact.actions.map((a) => (a.id === actionId ? { ...a, ...patch } : a)),
      })),
    );
  }, []);

  function setError(actionId: number, err: unknown, fallbackEn: string, fallbackAr: string) {
    const text = errorText(err);
    setErrors((prev) => ({ ...prev, [actionId]: { en: `${fallbackEn} ${text.en}`, ar: `${fallbackAr} ${text.ar}` } }));
    return text;
  }

  function clearError(actionId: number) {
    setErrors((prev) => ({ ...prev, [actionId]: null }));
  }

  function bumpTimeline() {
    setTimelineVersion((v) => v + 1);
  }

  async function handleApprove(actionId: number) {
    setBusy({ id: actionId, kind: "approve" });
    clearError(actionId);
    try {
      // Not optimistic: the agent really edits a file, so wait for the server result.
      const result = await approveAction(actionId);
      patchAction(actionId, { status: result.status as ActionStatus, can_undo: true, is_redo: false, effect: result.effect ?? null });
      setReverted((prev) => ({ ...prev, [actionId]: null }));
      setCaveats((prev) => ({ ...prev, [actionId]: [] }));
      setNotes((prev) => ({ ...prev, [actionId]: result.effect_note ? effectNoteBi(result.effect_note) : null }));
      if (result.effect) {
        const { added, removed, path } = result.effect;
        toast.success(
          <Bi
            en={<>The agent edited <bdi className="mono">{path}</bdi> (+{added}, {"−"}{removed}). Review the receipt below.</>}
            ar={<>عدّل الوكيل الملف <bdi className="mono">{path}</bdi> (+{added}، {"−"}{removed}). راجع الإيصال أدناه.</>}
          />,
        );
      } else {
        const note = result.effect_note ? effectNoteBi(result.effect_note) : null;
        toast.info(
          <Bi
            en={<>Approved and recorded. No file was changed.{note ? ` ${note.en}` : ""}</>}
            ar={<>اعتُمد الإجراء وسُجّل. لم يُغيَّر أي ملف.{note ? ` ${note.ar}` : ""}</>}
          />,
        );
      }
      bumpTimeline();
    } catch (err) {
      const text = setError(actionId, err, "Could not approve.", "تعذّر الاعتماد.");
      toast.error(<Bi en={`Could not approve the action. ${text.en}`} ar={`تعذّر اعتماد الإجراء. ${text.ar}`} />);
    } finally {
      setBusy(null);
    }
  }

  async function handleDismiss(actionId: number, reason: string) {
    setBusy({ id: actionId, kind: "dismiss" });
    clearError(actionId);
    try {
      const result = await dismissAction(actionId, reason);
      patchAction(actionId, { status: result.status as ActionStatus, can_undo: true, is_redo: false, dismiss_reason: result.reason ?? reason });
      toast.success(<Bi en="Action dismissed." ar="تم تجاهل الإجراء." />);
      bumpTimeline();
    } catch (err) {
      const text = setError(actionId, err, "Could not dismiss.", "تعذّر التجاهل.");
      toast.error(<Bi en={`Could not dismiss the action. ${text.en}`} ar={`تعذّر تجاهل الإجراء. ${text.ar}`} />);
    } finally {
      setBusy(null);
    }
  }

  async function handleConfirm(actionId: number) {
    setBusy({ id: actionId, kind: "confirm" });
    clearError(actionId);
    try {
      const result = await confirmAction(actionId);
      patchAction(actionId, { status: result.status as ActionStatus, confirmed_at: new Date().toISOString(), can_undo: true, is_redo: false });
      toast.success(<Bi en="Marked as done." ar="تم وضع علامة الإنجاز." />);
      bumpTimeline();
    } catch (err) {
      const text = setError(actionId, err, "Could not confirm.", "تعذّر التأكيد.");
      toast.error(<Bi en={`Could not mark it as done. ${text.en}`} ar={`تعذّر وضع علامة الإنجاز. ${text.ar}`} />);
    } finally {
      setBusy(null);
    }
  }

  async function handleUndo(actionId: number) {
    setBusy({ id: actionId, kind: "undo" });
    clearError(actionId);
    try {
      const result = await undoAction(actionId);
      // Mirrors routes/actions.py: reverting a delegation (previous status "pending") clears the assignee.
      const clearsAssignee = result.status === "pending";
      patchAction(actionId, {
        status: result.status as ActionStatus,
        can_undo: true,
        is_redo: true,
        effect: result.effect_reapplied ?? null,
        ...(clearsAssignee ? { assignee_name: null, assignee_contact: null, delegated_at: null, erp: null } : {}),
      });
      setReverted((prev) => ({ ...prev, [actionId]: result.effect_reverted ?? null }));
      setCaveats((prev) => ({ ...prev, [actionId]: result.side_effects_not_reversed }));
      if (result.effect_reverted) {
        toast.success(
          <Bi
            en={<>Undone: <bdi className="mono">{result.effect_reverted.path}</bdi> is back to its earlier content.</>}
            ar={<>تم التراجع: عاد الملف <bdi className="mono">{result.effect_reverted.path}</bdi> إلى محتواه السابق.</>}
          />,
        );
      } else if (result.effect_reapplied) {
        toast.success(
          <Bi
            en={<>Redone: the agent applied its edit to <bdi className="mono">{result.effect_reapplied.path}</bdi> again.</>}
            ar={<>تمت الإعادة: طبّق الوكيل تعديله على الملف <bdi className="mono">{result.effect_reapplied.path}</bdi> مجددًا.</>}
          />,
        );
      } else {
        toast.success(<Bi en="Status reverted." ar="أُعيدت الحالة السابقة." />);
      }
      if (result.side_effects_not_reversed.length > 0) {
        toast.warning(
          <Bi
            en={`Not reversible: ${result.side_effects_not_reversed.join(", ")}.`}
            ar={`لا يمكن التراجع عن: ${result.side_effects_not_reversed.join("، ")}.`}
          />,
        );
      }
      bumpTimeline();
    } catch (err) {
      const text = setError(actionId, err, "Could not undo.", "تعذّر التراجع.");
      toast.error(<Bi en={`Could not undo. ${text.en}`} ar={`تعذّر التراجع. ${text.ar}`} />);
    } finally {
      setBusy(null);
    }
  }

  async function reloadImpacts() {
    const fresh = await getChange(detail.id);
    setImpacts(fresh.impacts);
  }

  async function handleRefreshErp(actionId: number) {
    setErpRefreshing(actionId);
    setErpErrors((prev) => ({ ...prev, [actionId]: null }));
    try {
      await syncErp();
      await reloadImpacts();
      toast.success(<Bi en="ERP status refreshed from Odoo." ar="حُدّثت حالة المهمة من نظام Odoo." />);
      bumpTimeline();
    } catch (err) {
      const text = errorText(err);
      setErpErrors((prev) => ({ ...prev, [actionId]: text }));
      toast.error(<Bi en={`Could not refresh from Odoo. ${text.en}`} ar={`تعذّر التحديث من نظام Odoo. ${text.ar}`} />);
    } finally {
      setErpRefreshing(null);
    }
  }

  async function submitOdoo(action: ActionOut, employeeId: number, note: string): Promise<AssignResult> {
    try {
      const result = await delegateToOdoo(action.id, employeeId, note);
      patchAction(action.id, {
        status: result.status as ActionStatus,
        assignee_name: result.assignee_name,
        assignee_contact: result.assignee_contact,
        delegated_at: new Date().toISOString(),
        erp: result.erp ?? null,
        can_undo: true,
        is_redo: false,
      });
      setAssignTarget(null);
      const taskNo = result.erp?.task_id;
      toast.success(
        <Bi
          en={<>Task {taskNo != null ? <bdi className="mono">#{taskNo}</bdi> : ""} created in Odoo and assigned to <bdi>{result.assignee_name}</bdi>.</>}
          ar={<>أُنشئت المهمة {taskNo != null ? <bdi className="mono">#{taskNo}</bdi> : ""} في Odoo وأُسندت إلى <bdi>{result.assignee_name}</bdi>.</>}
        />,
      );
      bumpTimeline();
      return { ok: true };
    } catch (err) {
      const text = errorText(err);
      toast.error(<Bi en={`Odoo task was not created. ${text.en}`} ar={`لم تُنشأ المهمة في Odoo. ${text.ar}`} />);
      return { ok: false, error: text };
    }
  }

  async function submitManual(action: ActionOut, name: string, contact: string, message: string): Promise<AssignResult> {
    try {
      const result = await delegateAction(action.id, {
        assignee_name: name,
        assignee_contact: contact || null,
        message: message || null,
      });
      patchAction(action.id, {
        status: result.status as ActionStatus,
        assignee_name: result.assignee_name,
        assignee_contact: result.assignee_contact,
        delegated_at: new Date().toISOString(),
        erp: null,
        can_undo: true,
        is_redo: false,
      });
      setAssignTarget(null);
      toast.success(
        <Bi en={<>Assigned to <bdi>{name}</bdi>.</>} ar={<>أُسند الإجراء إلى <bdi>{name}</bdi>.</>} />,
      );
      bumpTimeline();
      return { ok: true };
    } catch (err) {
      const text = errorText(err);
      toast.error(<Bi en={`Could not assign. ${text.en}`} ar={`تعذّر الإسناد. ${text.ar}`} />);
      return { ok: false, error: text };
    }
  }

  function uiState(actionId: number): ActionUiState {
    return {
      busy: busy && busy.id === actionId ? busy.kind : busy ? ("delegate" as BusyKind) : null,
      effectNote: notes[actionId] ?? null,
      reverted: reverted[actionId] ?? null,
      caveats: caveats[actionId],
      error: errors[actionId] ?? null,
      erpRefreshing: erpRefreshing === actionId,
      erpRefreshError: erpErrors[actionId] ?? null,
    };
  }

  function openAction(actionId: number) {
    setTab("impact");
    window.setTimeout(() => {
      const el = document.getElementById(`action-${actionId}`);
      if (!el) return;
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      el.classList.add("is-flash");
      window.setTimeout(() => el.classList.remove("is-flash"), 1800);
    }, 60);
  }

  const actionsTotal = impacts.reduce((n, i) => n + i.actions.length, 0);
  const actionsPending = impacts.reduce((n, i) => n + i.actions.filter((a) => a.status === "pending").length, 0);

  // ---------- inline (row expand) stays lightweight: no impacted-node dump ----------
  if (mode === "inline") {
    return (
      <div className="detail chg-inline">
        {hasClauseText && (
          <ClauseDiff oldText={detail.old_text_en} newText={detail.new_text_en} ops={detail.diff_ops} oldLabel={detail.old_version_label} newLabel={detail.new_version_label} />
        )}
        <p className="chg-inline-summary"><Bi en={detail.summary_en} ar={<Isolated text={detail.summary_ar} />} /></p>
        <p className="chg-inline-prov">
          <Badge variant="neutral"><Bi en="Detected by code" ar="رصدها الكود" />: <Bi en={match.en} ar={match.ar} /></Badge>
          {detail.confidence != null && (
            <Badge variant="neutral"><Bi en="Model confidence" ar="ثقة النموذج" /> <span className="tabular">{Math.round(detail.confidence * 100)}%</span></Badge>
          )}
          {impacts.length > 0 && (
            <Badge variant="neutral">
              <Bi en={`${impacts.length} impacted, ${actionsTotal} actions`} ar={`${impacts.length} متأثر، ${actionsTotal} إجراء`} />
            </Badge>
          )}
        </p>
        <div className="chg-inline-buttons">
          <Button href={`/changes/${detail.id}`} variant="primary" size="sm" icon={<Icon icon={ListTree} size={15} />}>
            <Bi en="Review impact and decide" ar="مراجعة الأثر واتخاذ القرار" />
          </Button>
          {EXPORTS.map((e) => (
            <a key={e.key} className={buttonClass({ variant: "secondary", size: "sm" })} href={`/api/changes/${detail.id}/export/${e.key}`}>
              <Bi en={e.en} ar={e.ar} />
            </a>
          ))}
        </div>
      </div>
    );
  }

  // ---------- full page ----------
  return (
    <div className="chg-detail">
      <ProvenanceStrip detail={detail} />

      <Card className="chg-summary" title={<Bi en="Plain-language summary" ar="الملخص بلغة مبسطة" />}>
        <p className="chg-summary-text"><Bi en={detail.summary_en} ar={<Isolated text={detail.summary_ar} />} /></p>
        <p className="chg-citation">
          {detail.from_file_sha256 && (
            <span>
              <b>{detail.old_version_label ?? <Bi en="Previous doc" ar="المستند السابق" />}</b>{" "}
              {detail.old_page != null && <span className="tabular">p.{detail.old_page} · </span>}
              <bdi className="mono">{detail.from_file_sha256.slice(0, 10)}…{detail.from_file_sha256.slice(-6)}</bdi>
            </span>
          )}
          {detail.to_file_sha256 && (
            <span>
              <b>{detail.new_version_label ?? <Bi en="New doc" ar="المستند الجديد" />}</b>{" "}
              {detail.new_page != null && <span className="tabular">p.{detail.new_page} · </span>}
              <bdi className="mono">{detail.to_file_sha256.slice(0, 10)}…{detail.to_file_sha256.slice(-6)}</bdi>
            </span>
          )}
        </p>
        <CitationBadges detail={detail} />
      </Card>

      {hasClauseText && (
        <section aria-label={t(lang, "Old versus new clause", "البند القديم مقابل الجديد")}>
          <h2 className="xp-section-title"><Bi en="Old versus new clause" ar="البند القديم مقابل الجديد" /></h2>
          <ClauseDiff oldText={detail.old_text_en} newText={detail.new_text_en} ops={detail.diff_ops} oldLabel={detail.old_version_label} newLabel={detail.new_version_label} />
        </section>
      )}

      <PriorityBreakdown detail={detail} />

      <div className="chg-tabs-wrap">
        <Tabs<TabKey>
          value={tab}
          onChange={setTab}
          prefix="chg"
          ariaLabel={t(lang, "Change details", "تفاصيل التغيير")}
          tabs={[
            { value: "impact", label: <Bi en="Impact" ar="الأثر" />, count: impacts.length, icon: <Icon icon={GitPullRequestArrow} size={15} flipRtl /> },
            { value: "timeline", label: <Bi en="Timeline" ar="الخط الزمني" />, icon: <Icon icon={History} size={15} /> },
            { value: "exports", label: <Bi en="Exports" ar="التصدير" />, icon: <Icon icon={Download} size={15} /> },
          ]}
        />
        {tab === "impact" && <StatusCounts impacts={impacts} />}
      </div>

      <div role="tabpanel" id={panelId("chg", "impact")} aria-labelledby={tabId("chg", "impact")} hidden={tab !== "impact"} className="chg-panel">
        {tab === "impact" && (
          <ImpactList
            impacts={impacts}
            uiState={uiState}
            handlers={{
              onApprove: handleApprove,
              onDismiss: handleDismiss,
              onAssign: (actionId, impact) => {
                const action = impact.actions.find((a) => a.id === actionId);
                if (action) setAssignTarget({ action, impact });
              },
              onConfirm: handleConfirm,
              onUndo: handleUndo,
              onRefreshErp: handleRefreshErp,
            }}
          />
        )}
      </div>
      <div role="tabpanel" id={panelId("chg", "timeline")} aria-labelledby={tabId("chg", "timeline")} hidden={tab !== "timeline"} className="chg-panel">
        {tab === "timeline" && <Timeline changeId={detail.id} version={timelineVersion} onOpenAction={openAction} />}
      </div>
      <div role="tabpanel" id={panelId("chg", "exports")} aria-labelledby={tabId("chg", "exports")} hidden={tab !== "exports"} className="chg-panel">
        {tab === "exports" && <ExportButtons changeId={detail.id} />}
      </div>

      <AssignModal
        open={assignTarget !== null}
        action={assignTarget?.action ?? null}
        nodeId={assignTarget?.impact.node_id ?? null}
        nodeName={assignTarget?.impact.node_name ?? ""}
        onClose={() => setAssignTarget(null)}
        onSubmitOdoo={(employeeId, note) => (assignTarget ? submitOdoo(assignTarget.action, employeeId, note) : Promise.resolve({ ok: false, error: { en: "No action selected.", ar: "لم يُحدَّد إجراء." } }))}
        onSubmitManual={(name, contact, message) => (assignTarget ? submitManual(assignTarget.action, name, contact, message) : Promise.resolve({ ok: false, error: { en: "No action selected.", ar: "لم يُحدَّد إجراء." } }))}
      />

      {queue && <QueueBar queue={queue} changeId={detail.id} pending={actionsPending} total={actionsTotal} />}
    </div>
  );
}
