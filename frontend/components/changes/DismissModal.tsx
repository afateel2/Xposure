"use client";

import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { Bi } from "@/components/Bi";
import { Button, Field, Icon, Modal, Textarea } from "@/components/ui";
import { MAX_REASON_CHARS, MIN_REASON_CHARS, cleanReason, reasonIsValid } from "@/lib/reason";
import { t, useLang } from "@/lib/lang";

/**
 * Dismissing an action is a decision that leaves a record, so it needs a
 * reason: the audit log should answer "why was this not acted on?" and not
 * only "who dismissed it". The confirm button stays disabled until a reason is
 * written, and the dialog says why (a disabled control with no explanation
 * reads as a broken page).
 */
export function DismissModal({
  open, busy, onClose, onConfirm,
}: {
  open: boolean;
  busy: boolean;
  onClose: () => void;
  onConfirm: (reason: string) => void;
}) {
  const lang = useLang();
  const [reason, setReason] = useState("");

  useEffect(() => {
    if (open) setReason("");
  }, [open]);

  const valid = reasonIsValid(reason);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={<Bi en="Dismiss this action?" ar="تجاهل هذا الإجراء؟" />}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            <Bi en="Keep it" ar="إبقاء الإجراء" />
          </Button>
          <Button
            variant="danger"
            icon={<Icon icon={X} size={16} />}
            disabled={!valid}
            loading={busy}
            onClick={() => onConfirm(cleanReason(reason))}
          >
            <Bi en="Dismiss action" ar="تجاهل الإجراء" />
          </Button>
        </>
      }
    >
      <p>
        <Bi
          en="No action will be taken for this item. The decision is recorded in the audit log under your name, together with the reason below. You can undo it later."
          ar="لن يُتخذ أي إجراء بشأن هذا العنصر. يُسجَّل القرار في سجل التدقيق باسمك مع السبب المكتوب أدناه، ويمكنك التراجع عنه لاحقًا."
        />
      </p>
      <Field
        label={<Bi en="Reason for dismissing (required)" ar="سبب التجاهل (مطلوب)" />}
        htmlFor="dismiss-reason"
        hint={
          valid ? (
            <Bi en="The reason is logged in your name." ar="يُسجَّل السبب باسمك." />
          ) : (
            <Bi
              en={`Dismiss stays disabled until you write a reason (at least ${MIN_REASON_CHARS} characters).`}
              ar={`يبقى زر التجاهل معطّلًا حتى تكتب سببًا (لا يقل عن ${MIN_REASON_CHARS} أحرف).`}
            />
          )
        }
      >
        <Textarea
          id="dismiss-reason"
          autoFocus
          value={reason}
          maxLength={MAX_REASON_CHARS}
          onChange={(e) => setReason(e.target.value)}
          placeholder={t(lang, "For example: already covered by the existing procedure, evidence attached.", "مثال: مغطّى بالفعل بالإجراء القائم، والدليل مرفق.")}
        />
      </Field>
    </Modal>
  );
}
