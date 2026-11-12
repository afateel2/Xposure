"use client";

import { useState } from "react";
import { Bot, CircleCheck, Undo2, UserPlus, X } from "lucide-react";
import { Bi } from "@/components/Bi";
import { Badge, Button, Icon, Modal, actionStatusVariant } from "@/components/ui";
import { ACTION_STATUS_LABEL, ACTION_TYPE_LABEL, AUTOMATION_GATE_LABEL, AUTOMATION_LEVEL_LABEL } from "@/lib/labels";
import type { ActionEffect } from "@/lib/types-shared";
import type { ActionOut } from "@/lib/types";
import { ActionReceipt } from "./ActionReceipt";
import { DismissModal } from "./DismissModal";
import { ErpCard } from "./ErpCard";
import type { ErpErrorNote } from "./erp-types";
import { FILE_EDIT_ACTION_TYPES } from "./labels";
import { RelTime } from "./RelTime";

export type BusyKind = "approve" | "dismiss" | "undo" | "confirm" | "delegate";

export interface RevertedEffect extends ActionEffect {
  reverted_at?: string;
  version_restored?: number;
}

export interface ActionCardProps {
  action: ActionOut;
  nodeType: string;
  busy: BusyKind | null;
  /** Reason the last approval had no file effect (only known right after approving). */
  effectNote?: { en: string; ar: string } | null;
  reverted?: RevertedEffect | null;
  caveats?: string[];
  error?: ErpErrorNote | null;
  erpRefreshing: boolean;
  erpRefreshError?: ErpErrorNote | null;
  onApprove: () => void;
  /** Called with the reviewer's written reason, after the dismiss dialog is confirmed. */
  onDismiss: (reason: string) => void;
  onAssign: () => void;
  onConfirm: () => void;
  onUndo: () => void;
  onRefreshErp: () => void;
}

/**
 * One suggested action on an impacted node. Pending actions offer a real
 * choice (the agent handles it, assign to a person, dismiss); everything that
 * was transitioned shows its outcome (receipt, ERP task, completion) and keeps
 * an Undo. Exactly one primary button per card.
 */
export function ActionCard(props: ActionCardProps) {
  const { action, nodeType, busy, effectNote, reverted, caveats, error, erpRefreshing, erpRefreshError } = props;
  const [confirmUndo, setConfirmUndo] = useState(false);
  const [confirmDismiss, setConfirmDismiss] = useState(false);
  const typeLabel = ACTION_TYPE_LABEL[action.type];
  const statusLabel =
    action.status === "done"
      ? action.confirmed_at
        ? { en: "Done", ar: "منجز" }
        : { en: "Done (auto)", ar: "منجز (تلقائي)" }
      : ACTION_STATUS_LABEL[action.status];
  const isFileEdit = FILE_EDIT_ACTION_TYPES.has(action.type);
  // notify_owner is about a person, not a file: escalating to a person is the natural primary.
  const assignIsPrimary = action.type === "notify_owner";
  const showErp = !!action.erp && (action.status === "awaiting_confirmation" || action.status === "done");
  const hasLiveEffect = !!action.effect && action.status === "approved";
  const undoNeedsConfirm = hasLiveEffect || showErp;
  const undoLabel = action.is_redo || action.status === "pending" ? { en: "Redo", ar: "إعادة" } : { en: "Undo", ar: "تراجع" };
  const anyBusy = busy !== null;

  function requestUndo() {
    if (undoNeedsConfirm) setConfirmUndo(true);
    else props.onUndo();
  }

  const undoButton = (
    <Button variant="secondary" size="sm" icon={<Icon icon={Undo2} size={14} flipRtl />} disabled={anyBusy && busy !== "undo"} loading={busy === "undo"} onClick={requestUndo}>
      <Bi en={undoLabel.en} ar={undoLabel.ar} />
    </Button>
  );

  return (
    <div className="chg-action" id={`action-${action.id}`} data-status={action.status}>
      <div className="chg-action-head">
        <span className="chg-action-type">
          <span className="chg-action-kicker"><Bi en="Suggested action" ar="الإجراء المقترح" /></span>
          <b>{typeLabel ? <Bi en={typeLabel.en} ar={typeLabel.ar} /> : action.type}</b>
        </span>
        <Badge variant={actionStatusVariant(action.status)}>
          {statusLabel ? <Bi en={statusLabel.en} ar={statusLabel.ar} /> : action.status}
        </Badge>
        <span className="chg-chip">
          {AUTOMATION_LEVEL_LABEL[action.level] ? <Bi en={AUTOMATION_LEVEL_LABEL[action.level].en} ar={AUTOMATION_LEVEL_LABEL[action.level].ar} /> : action.level}
        </span>
        {action.owner_node_name && nodeType !== "owner" && <span className="chg-chip"><Bi en="Owner" ar="المالك" />: <bdi>{action.owner_node_name}</bdi></span>}
      </div>

      {action.automation_gates && action.automation_gates.length > 0 && (
        <p className="xp-muted chg-action-why">
          <Bi en="Why this level: " ar="سبب هذا المستوى: " />
          {action.automation_gates
            .map((g) => AUTOMATION_GATE_LABEL[g])
            .filter((l): l is { en: string; ar: string } => Boolean(l))
            .map((l, i, arr) => (
              <span key={i}>
                <Bi en={l.en} ar={l.ar} />
                {i < arr.length - 1 ? <Bi en=", " ar="، " /> : null}
              </span>
            ))}
          {action.automation_requested && action.automation_requested !== action.level && (
            <>
              {" "}
              <Bi
                en={<>(the policy asked for {AUTOMATION_LEVEL_LABEL[action.automation_requested]?.en ?? action.automation_requested})</>}
                ar={<>(طلبت السياسة <bdi>{AUTOMATION_LEVEL_LABEL[action.automation_requested]?.ar ?? action.automation_requested}</bdi>)</>}
              />
            </>
          )}
        </p>
      )}

      {action.status === "pending" && (
        <div className="chg-action-body">
          <p className="chg-action-hint">
            {isFileEdit ? (
              <Bi
                en="The agent edits the mapped company file. You review the diff and can undo it."
                ar="يعدّل الوكيل الملف المرتبط في بيانات المنشأة، وتراجع أنت الفروقات ويمكنك التراجع عنها."
              />
            ) : action.type === "notify_owner" ? (
              <Bi
                en="Assign it to the responsible person. The agent has no file to change for this action."
                ar="أسنده إلى الشخص المسؤول. لا يوجد ملف يغيّره الوكيل في هذا الإجراء."
              />
            ) : (
              <Bi
                en="If the agent handles it, the approval is recorded as a decision. It does not change any file."
                ar="إذا تولّى الوكيل الأمر فيُسجَّل الاعتماد كقرار فقط ولا يغيّر أي ملف."
              />
            )}
          </p>
          <div className="chg-action-buttons">
            <Button
              variant={assignIsPrimary ? "secondary" : "primary"}
              icon={<Icon icon={Bot} size={16} />}
              loading={busy === "approve"}
              disabled={anyBusy && busy !== "approve"}
              onClick={props.onApprove}
            >
              <Bi en="Let the agent handle it" ar="ترك الوكيل يتولى الأمر" />
            </Button>
            <Button
              variant={assignIsPrimary ? "primary" : "secondary"}
              icon={<Icon icon={UserPlus} size={16} />}
              disabled={anyBusy}
              onClick={props.onAssign}
            >
              <Bi en="Assign to a person" ar="إسناد إلى شخص" />
            </Button>
            <Button variant="ghost" icon={<Icon icon={X} size={16} />} loading={busy === "dismiss"} disabled={anyBusy && busy !== "dismiss"} onClick={() => setConfirmDismiss(true)}>
              <Bi en="Dismiss" ar="تجاهل" />
            </Button>
            {action.can_undo && undoButton}
          </div>
          {busy === "approve" && (
            <p className="chg-action-working" role="status">
              <Bi
                en={isFileEdit ? "The agent is editing the file. This can take a few seconds." : "Recording the approval..."}
                ar={isFileEdit ? "يعدّل الوكيل الملف الآن، وقد يستغرق ذلك بضع ثوانٍ." : "جارٍ تسجيل الاعتماد..."}
              />
            </p>
          )}
        </div>
      )}

      {reverted && (
        <div className="eff-reverted" role="status">
          <Icon icon={Undo2} size={16} flipRtl />
          <span>
            <Bi
              en={<>The agent&apos;s edit to <bdi className="mono">{reverted.path}</bdi> was reverted. The file is back to its earlier content{reverted.version_restored != null ? <> (restored as <bdi className="mono">v{reverted.version_restored}</bdi>)</> : null}.</>}
              ar={<>تم التراجع عن تعديل الوكيل للملف <bdi className="mono">{reverted.path}</bdi>، وعاد الملف إلى محتواه السابق{reverted.version_restored != null ? <> (أُعيد كإصدار <bdi className="mono">v{reverted.version_restored}</bdi>)</> : null}.</>}
            />
          </span>
        </div>
      )}

      {action.status === "approved" && (
        <div className="chg-action-body">
          {action.effect ? (
            <ActionReceipt effect={action.effect} undoBusy={busy === "undo"} onUndo={requestUndo} />
          ) : (
            <>
              <p className="chg-action-outcome">
                <Icon icon={CircleCheck} size={16} />
                <span>
                  <Bi en="Approved and recorded as a decision. The agent did not change any company file." ar="اعتُمد وسُجّل كقرار. لم يغيّر الوكيل أي ملف في بيانات المنشأة." />
                  {effectNote && <span className="xp-muted"> <Bi en={effectNote.en} ar={effectNote.ar} /></span>}
                </span>
              </p>
              <div className="chg-action-buttons">{undoButton}</div>
            </>
          )}
        </div>
      )}

      {action.status === "dismissed" && (
        <div className="chg-action-body">
          <p className="chg-action-outcome is-muted">
            <Icon icon={X} size={16} />
            <span>
              <Bi en="Dismissed. No action will be taken." ar="تم التجاهل. لن يُتخذ أي إجراء." />
              {action.dismiss_reason && (
                <span className="chg-action-reason">
                  <b><Bi en="Reason:" ar="السبب:" /></b> <bdi>{action.dismiss_reason}</bdi>
                </span>
              )}
            </span>
          </p>
          <div className="chg-action-buttons">{undoButton}</div>
        </div>
      )}

      {(action.status === "awaiting_confirmation" || action.status === "done") && (
        <div className="chg-action-body">
          {showErp && action.erp ? (
            <ErpCard
              erp={action.erp}
              assigneeFallback={action.assignee_name}
              refreshing={erpRefreshing}
              refreshError={erpRefreshError}
              onRefresh={props.onRefreshErp}
            />
          ) : (
            action.assignee_name && (
              <p className="chg-action-outcome">
                <Icon icon={UserPlus} size={16} />
                <span>
                  <Bi en="Assigned to" ar="مُسنَد إلى" /> <b><bdi>{action.assignee_name}</bdi></b>
                  {action.assignee_contact && <> <span className="xp-muted mono" dir="ltr">{action.assignee_contact}</span></>}
                  {action.delegated_at && <span className="xp-muted"> · <RelTime value={action.delegated_at} /></span>}
                </span>
              </p>
            )
          )}

          {action.status === "done" && (
            <p className="chg-action-outcome is-done">
              <Icon icon={CircleCheck} size={16} />
              <span>
                {action.confirmed_at ? (
                  <Bi en="Completion confirmed" ar="تم تأكيد الإنجاز" />
                ) : (
                  <Bi en="Completed automatically" ar="أُنجز تلقائيًا" />
                )}
                {action.confirmed_at && <span className="xp-muted"> · <RelTime value={action.confirmed_at} /></span>}
              </span>
            </p>
          )}

          <div className="chg-action-buttons">
            {action.status === "awaiting_confirmation" && (
              <Button variant="primary" size="sm" icon={<Icon icon={CircleCheck} size={15} />} loading={busy === "confirm"} disabled={anyBusy && busy !== "confirm"} onClick={props.onConfirm}>
                <Bi en="Mark as done" ar="وضع علامة كمُنجَز" />
              </Button>
            )}
            {undoButton}
          </div>
        </div>
      )}

      {caveats && caveats.length > 0 && (
        <p className="chg-action-caveat">
          <Bi
            en={`Undone here, but not reversible: ${caveats.join(", ")}.`}
            ar={`تم التراجع هنا، لكن لا يمكن التراجع عن: ${caveats.join("، ")}.`}
          />
        </p>
      )}

      {error && (
        <p className="xp-error chg-action-error" role="alert">
          <Bi en={error.en} ar={error.ar} />
        </p>
      )}

      <DismissModal
        open={confirmDismiss}
        busy={busy === "dismiss"}
        onClose={() => setConfirmDismiss(false)}
        onConfirm={(reason) => {
          setConfirmDismiss(false);
          props.onDismiss(reason);
        }}
      />

      <Modal
        open={confirmUndo}
        onClose={() => setConfirmUndo(false)}
        title={
          hasLiveEffect ? (
            <Bi en="Undo the agent's edit?" ar="التراجع عن تعديل الوكيل؟" />
          ) : (
            <Bi en="Undo the assignment?" ar="التراجع عن الإسناد؟" />
          )
        }
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmUndo(false)}>
              <Bi en="Keep it" ar="إبقاء الوضع الحالي" />
            </Button>
            <Button
              variant="primary"
              icon={<Icon icon={Undo2} size={16} flipRtl />}
              onClick={() => {
                setConfirmUndo(false);
                props.onUndo();
              }}
            >
              <Bi en="Undo" ar="تراجع" />
            </Button>
          </>
        }
      >
        {hasLiveEffect && action.effect ? (
          <Bi
            en={<>The file <bdi className="mono">{action.effect.path}</bdi> is restored to its content before the edit (as a new version, so the history is kept), and the action goes back to pending. If the file was changed again since, it is left as it is and you are told.</>}
            ar={<>يُستعاد الملف <bdi className="mono">{action.effect.path}</bdi> إلى محتواه قبل التعديل (كإصدار جديد فيبقى السجل محفوظًا)، ويعود الإجراء إلى حالة الانتظار. وإذا تغيّر الملف بعد ذلك فيُترك كما هو ويُبلَّغ بذلك.</>}
          />
        ) : (
          <Bi
            en={<>This reverts the status in Xposure only. {action.erp ? <>The task <bdi className="mono">#{action.erp.task_id}</bdi> already created in Odoo is not deleted, and any notification that was sent cannot be recalled.</> : <>Any notification that was already sent cannot be recalled.</>}</>}
            ar={<>يُعاد هنا حال الإجراء في Xposure فقط. {action.erp ? <>لا تُحذف المهمة <bdi className="mono">#{action.erp.task_id}</bdi> التي أُنشئت في Odoo، ولا يمكن استرجاع أي إشعار أُرسل.</> : <>ولا يمكن استرجاع أي إشعار أُرسل مسبقًا.</>}</>}
          />
        )}
      </Modal>
    </div>
  );
}
