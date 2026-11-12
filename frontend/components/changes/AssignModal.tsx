"use client";

import { useEffect, useId, useState } from "react";
import { Mail, Server, UserPlus, Waypoints } from "lucide-react";
import { Bi } from "@/components/Bi";
import { Button, Field, Icon, Input, Modal, Select, Textarea } from "@/components/ui";
import { ApiError, erpIsConnected, errorText, getErpEmployees, getErpStatus, getNodeOwner, type ErpStatusFull, type NodeOwner } from "@/lib/api-erp";
import { t, useLang } from "@/lib/lang";
import type { ErpEmployee } from "@/lib/types-shared";
import { ACTION_TYPE_LABEL } from "@/lib/labels";
import type { ActionOut } from "@/lib/types";
import type { ErpErrorNote } from "./erp-types";
import { Tabs, panelId, tabId } from "./Tabs";

type Channel = "odoo" | "manual";

type ErpLoad =
  | { phase: "loading" }
  | { phase: "missing" }
  | { phase: "error"; note: ErpErrorNote }
  | { phase: "ready"; status: ErpStatusFull; employees: ErpEmployee[]; employeesError: ErpErrorNote | null };

export type AssignResult = { ok: true } | { ok: false; error: ErpErrorNote };

/** The employee that is the owner of this node: by work email (from the Facility profile), else by job title. */
function pickOwnerEmployee(employees: ErpEmployee[], email: string | null, ownerName: string | null): ErpEmployee | null {
  if (email) {
    const byEmail = employees.find((e) => (e.work_email ?? "").toLowerCase() === email.toLowerCase());
    if (byEmail) return byEmail;
  }
  if (ownerName) {
    const byTitle = employees.find((e) => (e.job_title ?? "").trim().toLowerCase() === ownerName.trim().toLowerCase());
    if (byTitle) return byTitle;
  }
  return null;
}

/**
 * "Assign to a person": two honest channels. Odoo creates a real task (the
 * status line tells the truth about connectivity, and the option disappears
 * with a reason when this server has no ERP integration); the other tab keeps
 * the original name, contact and message flow.
 */
export function AssignModal({
  open, action, nodeId, nodeName, onClose, onSubmitOdoo, onSubmitManual,
}: {
  open: boolean;
  action: ActionOut | null;
  nodeId: number | null;
  nodeName: string;
  onClose: () => void;
  onSubmitOdoo: (employeeId: number, note: string) => Promise<AssignResult>;
  onSubmitManual: (name: string, contact: string, message: string) => Promise<AssignResult>;
}) {
  const lang = useLang();
  const uid = useId();
  const [channel, setChannel] = useState<Channel>("odoo");
  const [erp, setErp] = useState<ErpLoad>({ phase: "loading" });
  const [employeeId, setEmployeeId] = useState("");
  const [note, setNote] = useState("");
  const [name, setName] = useState("");
  const [contact, setContact] = useState("");
  const [message, setMessage] = useState("");
  const [triedManual, setTriedManual] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<ErpErrorNote | null>(null);
  const [preselected, setPreselected] = useState(false);
  const [suggestedOwner, setSuggestedOwner] = useState<NodeOwner | null>(null);

  // Reset and load the ERP situation every time the dialog opens.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setChannel("odoo");
    setErp({ phase: "loading" });
    setEmployeeId("");
    setNote("");
    setName("");
    setContact("");
    setMessage("");
    setTriedManual(false);
    setSubmitting(false);
    setError(null);
    setPreselected(false);
    setSuggestedOwner(null);

    // The org-graph suggestion is independent of ERP connectivity: it pre-fills
    // whichever channel the reviewer ends up on, Odoo or manual. Nothing is
    // written to the action; the reviewer still has to press Send/Create task.
    (async () => {
      if (nodeId === null) return;
      const owner = await getNodeOwner(nodeId);
      if (cancelled || !owner) return;
      setSuggestedOwner(owner);
      setName(owner.name);
      setContact(owner.email ?? "");
    })();

    (async () => {
      try {
        const status = await getErpStatus();
        if (cancelled) return;
        if (!erpIsConnected(status)) {
          setErp({ phase: "ready", status, employees: [], employeesError: null });
          return;
        }
        try {
          const employees = await getErpEmployees();
          if (cancelled) return;
          setErp({ phase: "ready", status, employees, employeesError: null });
          const owner = nodeId !== null ? await getNodeOwner(nodeId) : null;
          if (cancelled) return;
          const match = pickOwnerEmployee(employees, owner?.email ?? null, owner?.name ?? null);
          if (match) {
            setEmployeeId(String(match.id));
            setPreselected(true);
          }
        } catch (err) {
          if (!cancelled) setErp({ phase: "ready", status, employees: [], employeesError: errorText(err) });
        }
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setErp({ phase: "missing" });
          setChannel("manual");
        } else {
          setErp({ phase: "error", note: errorText(err) });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
    // The dialog is keyed by action in the parent; only (re)load when it opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const connected = erp.phase === "ready" && erpIsConnected(erp.status);
  const employees = erp.phase === "ready" ? erp.employees : [];
  const selected = employees.find((e) => String(e.id) === employeeId) ?? null;
  const showTabs = erp.phase !== "missing";
  const typeLabel = action ? ACTION_TYPE_LABEL[action.type] : null;

  async function submit() {
    setError(null);
    if (channel === "odoo") {
      if (!connected || !selected) return;
      setSubmitting(true);
      const res = await onSubmitOdoo(selected.id, note);
      setSubmitting(false);
      if (!res.ok) setError(res.error);
    } else {
      setTriedManual(true);
      if (name.trim() === "") return;
      setSubmitting(true);
      const res = await onSubmitManual(name.trim(), contact.trim(), message.trim());
      setSubmitting(false);
      if (!res.ok) setError(res.error);
    }
  }

  const canSubmit = channel === "odoo" ? connected && selected !== null : true;

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="lg"
      title={<Bi en="Assign to a person" ar="إسناد إلى شخص" />}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={submitting}>
            <Bi en="Cancel" ar="إلغاء" />
          </Button>
          <Button
            variant="primary"
            icon={<Icon icon={channel === "odoo" ? Server : Mail} size={16} />}
            loading={submitting}
            disabled={!canSubmit}
            onClick={submit}
          >
            {channel === "odoo" ? <Bi en="Create task in Odoo" ar="إنشاء مهمة في Odoo" /> : <Bi en="Send" ar="إرسال" />}
          </Button>
        </>
      }
    >
      <div className="chg-assign">
        {typeLabel && (
          <p className="chg-assign-ctx">
            <Bi en="Action:" ar="الإجراء:" /> <b><Bi en={typeLabel.en} ar={typeLabel.ar} /></b>
            {" "}
            <Bi en="on" ar="على" /> <bdi>{nodeName}</bdi>
          </p>
        )}

        {suggestedOwner && (
          <div className="chg-assign-suggestion" role="status">
            <Icon icon={Waypoints} size={16} />
            <span>
              <Bi en="Agent suggestion, from the organization graph: " ar="اقتراح الوكيل، من خريطة ارتباطات المنشأة: " />
              <b>{suggestedOwner.name}</b>
              {suggestedOwner.role && <> · <bdi>{suggestedOwner.role}</bdi></>}
              {suggestedOwner.email && <> · <bdi className="mono">{suggestedOwner.email}</bdi></>}
              {" "}
              <Bi
                en="This is who owns the affected item; choose someone else below if the agent got it wrong."
                ar="هذا هو مالك العنصر المتأثر. اختر شخصًا آخر أدناه إن أخطأ الوكيل."
              />
            </span>
          </div>
        )}

        {showTabs ? (
          <Tabs
            value={channel}
            onChange={setChannel}
            ariaLabel={t(lang, "How to assign", "طريقة الإسناد")}
            prefix={`assign-${uid}`}
            tabs={[
              { value: "odoo", label: <Bi en="Send to ERP (Odoo)" ar="إرسال إلى نظام ERP (Odoo)" />, icon: <Icon icon={Server} size={15} /> },
              { value: "manual", label: <Bi en="Notify by email or webhook" ar="إشعار بالبريد أو خطاف ويب" />, icon: <Icon icon={Mail} size={15} /> },
            ]}
          />
        ) : (
          <p className="chg-assign-why" role="note">
            <Bi
              en="The ERP option is hidden because this server has no ERP integration (GET /erp/status was not found)."
              ar={<>خيار نظام ERP مخفي لأن هذا الخادم لا يتضمن تكاملًا مع ERP (لم يُعثر على <bdi>/erp/status</bdi>).</>}
            />
          </p>
        )}

        {channel === "odoo" && showTabs && (
          <div role="tabpanel" id={panelId(`assign-${uid}`, "odoo")} aria-labelledby={tabId(`assign-${uid}`, "odoo")} className="chg-assign-panel">
            <div className={`erp-status${erp.phase === "ready" && connected ? " is-ok" : erp.phase === "loading" ? "" : " is-bad"}`} role="status" aria-live="polite">
              <i aria-hidden="true" />
              {erp.phase === "loading" && <Bi en="Checking the connection to Odoo..." ar="جارٍ فحص الاتصال بنظام Odoo..." />}
              {erp.phase === "error" && (
                <span><Bi en={`Could not read the ERP status. ${erp.note.en}`} ar={`تعذّرت قراءة حالة نظام ERP. ${erp.note.ar}`} /></span>
              )}
              {erp.phase === "ready" && connected && (
                <span>
                  <b><Bi en="Connected to Odoo" ar="متصل بنظام Odoo" /></b>
                  {erp.status.version && <span className="xp-muted"> <bdi>{erp.status.version}</bdi></span>}
                  {erp.status.database && <span className="xp-muted"> · <bdi className="mono">{erp.status.database}</bdi></span>}
                </span>
              )}
              {erp.phase === "ready" && !connected && (
                <span>
                  <b><Bi en="Odoo is not reachable" ar="نظام Odoo غير متاح" /></b>
                  <span className="xp-muted"> <Bi en={erp.status.message_en} ar={erp.status.message_ar} /></span>
                </span>
              )}
            </div>

            {erp.phase === "ready" && erp.employeesError && (
              <p className="xp-error" role="alert">
                <Bi en={`Could not load employees. ${erp.employeesError.en}`} ar={`تعذّر تحميل قائمة الموظفين. ${erp.employeesError.ar}`} />
              </p>
            )}

            <Field
              label={<Bi en="Assign to" ar="إسناد إلى" />}
              htmlFor={`${uid}-emp`}
              hint={
                selected ? (
                  <span>
                    {preselected && <b><Bi en="Owner of this item. " ar="مالك هذا العنصر. " /></b>}
                    {selected.job_title && <bdi>{selected.job_title}</bdi>}
                    {selected.department && <> · <bdi>{selected.department}</bdi></>}
                    {selected.work_email && <> · <bdi className="mono">{selected.work_email}</bdi></>}
                  </span>
                ) : undefined
              }
            >
              <Select id={`${uid}-emp`} value={employeeId} disabled={!connected || employees.length === 0} onChange={(e) => setEmployeeId(e.target.value)}>
                <option value="">{connected ? t(lang, "Choose a person", "اختر شخصًا") : t(lang, "Unavailable while Odoo is unreachable", "غير متاح أثناء انقطاع Odoo")}</option>
                {employees.map((e) => (
                  <option key={e.id} value={e.id}>{e.job_title ? `${e.name} (${e.job_title})` : e.name}</option>
                ))}
              </Select>
            </Field>
            <Field label={<Bi en="Note for the task" ar="ملاحظة للمهمة" />} htmlFor={`${uid}-note`} hint={<Bi en="Optional. Added to the task description in Odoo." ar="اختياري. تُضاف إلى وصف المهمة في Odoo." />}>
              <Textarea id={`${uid}-note`} rows={3} value={note} onChange={(e) => setNote(e.target.value)} disabled={!connected} />
            </Field>
            <p className="chg-assign-foot">
              <Bi
                en="A real task is created in Odoo. If Odoo refuses, nothing changes in Xposure."
                ar="تُنشأ مهمة حقيقية في Odoo. وإذا رفض Odoo الطلب فلن يتغير شيء في Xposure."
              />
            </p>
          </div>
        )}

        {channel === "manual" && (
          <div
            role={showTabs ? "tabpanel" : undefined}
            id={showTabs ? panelId(`assign-${uid}`, "manual") : undefined}
            aria-labelledby={showTabs ? tabId(`assign-${uid}`, "manual") : undefined}
            className="chg-assign-panel"
          >
            <div className="chg-assign-row">
              <Field
                label={<Bi en="Name" ar="الاسم" />}
                htmlFor={`${uid}-name`}
                error={triedManual && name.trim() === "" ? <Bi en="A name is required." ar="الاسم مطلوب." /> : null}
              >
                <Input id={`${uid}-name`} value={name} invalid={triedManual && name.trim() === ""} onChange={(e) => setName(e.target.value)} />
              </Field>
              <Field label={<Bi en="Email (optional)" ar="البريد الإلكتروني (اختياري)" />} htmlFor={`${uid}-contact`}>
                <Input id={`${uid}-contact`} type="email" dir="ltr" value={contact} onChange={(e) => setContact(e.target.value)} />
              </Field>
            </div>
            <Field label={<Bi en="Message (optional)" ar="رسالة (اختياري)" />} htmlFor={`${uid}-msg`}>
              <Textarea id={`${uid}-msg`} rows={3} value={message} onChange={(e) => setMessage(e.target.value)} />
            </Field>
            <p className="chg-assign-foot">
              <Icon icon={UserPlus} size={14} />{" "}
              <Bi
                en="Delivered via email if a notification channel is configured; otherwise this only records who it was assigned to."
                ar="يُرسَل عبر البريد الإلكتروني إذا كانت قناة الإشعارات مُفعّلة، وإلا فسيُسجَّل فقط اسم الشخص المُكلَّف بذلك."
              />
            </p>
          </div>
        )}

        <div aria-live="assertive">
          {error && (
            <p className="xp-error chg-assign-error" role="alert">
              <Bi en={`Could not assign. ${error.en}`} ar={`تعذّر الإسناد. ${error.ar}`} />
            </p>
          )}
        </div>
      </div>
    </Modal>
  );
}
