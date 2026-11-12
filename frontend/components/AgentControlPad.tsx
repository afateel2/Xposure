"use client";

import { useEffect, useState } from "react";
import { bulkAction, getSuggestions, previewCommand } from "@/lib/api";
import { t, useLang } from "@/lib/lang";
import { MAX_REASON_CHARS, MIN_REASON_CHARS, cleanReason, reasonIsValid } from "@/lib/reason";
import type { BulkActionResult, CommandPreviewOut, SuggestionOut } from "@/lib/types";
import { Bi } from "./Bi";
import { Badge, Button, CircleCheck, Field, Icon, Input, Search, Textarea } from "./ui";

/**
 * The one rule this whole component exists to enforce: free text is a
 * PREVIEW, never an execution. previewCommand() only ever reads and
 * proposes (backend/app/routes/agent_console.py's own docstring states the
 * same safety reasoning); the only call that can actually change anything
 * is bulkAction(), and it only ever fires from the explicit confirm button
 * below, never from the preview step itself.
 */
export function AgentControlPad() {
  const lang = useLang();
  const [suggestions, setSuggestions] = useState<SuggestionOut[]>([]);
  const [command, setCommand] = useState("");
  const [preview, setPreview] = useState<CommandPreviewOut | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [result, setResult] = useState<BulkActionResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  // A bulk dismissal needs a written reason, like a single one (the backend refuses it without).
  const [reason, setReason] = useState("");

  useEffect(() => {
    getSuggestions().then(setSuggestions).catch(() => setSuggestions([]));
  }, []);

  async function runPreview(text: string) {
    setCommand(text);
    setResult(null);
    setError(null);
    setReason("");
    if (text.trim() === "") {
      setPreview(null);
      return;
    }
    setPreviewing(true);
    try {
      const p = await previewCommand(text);
      setPreview(p);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setPreview(null);
    } finally {
      setPreviewing(false);
    }
  }

  async function handleConfirm() {
    if (!preview || (preview.proposed_decision !== "approve" && preview.proposed_decision !== "dismiss")) return;
    setConfirming(true);
    setError(null);
    try {
      const r = await bulkAction({
        action_ids: preview.matched_action_ids,
        decision: preview.proposed_decision,
        ...(preview.proposed_decision === "dismiss" ? { reason: cleanReason(reason) } : {}),
      });
      setResult(r);
      setPreview(null);
      setCommand("");
      setReason("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setConfirming(false);
    }
  }

  const canConfirm =
    preview &&
    (preview.proposed_decision === "approve" || preview.proposed_decision === "dismiss") &&
    preview.matched_action_ids.length > 0;
  const needsReason = preview?.proposed_decision === "dismiss";
  const reasonMissing = needsReason && !reasonIsValid(reason);

  return (
    <div className="run-pad">
      {suggestions.length > 0 && (
        <div className="run-pad-suggestions" role="group" aria-label={t(lang, "Suggested commands", "أوامر مقترحة")}>
          {suggestions.map((s) => (
            <Button key={s.id} variant="secondary" size="sm" onClick={() => runPreview(t(lang, s.text_en, s.text_ar))}>
              <Bi en={s.text_en} ar={s.text_ar} />
            </Button>
          ))}
        </div>
      )}

      <form
        className="run-pad-form"
        onSubmit={(e) => {
          e.preventDefault();
          runPreview(command);
        }}
      >
        <Input
          aria-label={t(lang, "Command for the agent", "أمر للوكيل")}
          placeholder={t(lang, "Type a command, e.g. \"approve the clarification changes\"", "اكتب أمرًا، مثل «اعتمد التغييرات التوضيحية»")}
          value={command}
          onChange={(e) => setCommand(e.target.value)}
        />
        <Button type="submit" variant="secondary" icon={<Icon icon={Search} size={16} />} loading={previewing} disabled={command.trim() === ""}>
          <Bi en="Preview" ar="معاينة" />
        </Button>
      </form>

      <div aria-live="polite">
        {error && (
          <p className="run-pad-error" role="alert">
            {error}
          </p>
        )}

        {preview && (
          <div className="run-preview">
            <div className="run-preview-head">
              <b>
                <Bi en={`${preview.matched_change_ids.length} change(s) matched`} ar={`تم مطابقة ${preview.matched_change_ids.length} تغييرًا`} />
              </b>
              {preview.proposed_decision && (
                <Badge variant="neutral">
                  <Bi
                    en={preview.proposed_decision}
                    ar={{ approve: "اعتماد", dismiss: "تجاهل", summarize: "تلخيص" }[preview.proposed_decision]}
                  />
                </Badge>
              )}
              <span className="run-preview-conf tabular">
                <Bi en="confidence" ar="مستوى الثقة" /> {Math.round(preview.confidence * 100)}%
              </span>
            </div>
            <p className="run-preview-text"><Bi en={preview.explanation_en} ar={preview.explanation_ar} /></p>

            {canConfirm && needsReason && (
              <Field
                className="run-pad-reason"
                label={<Bi en="Reason for dismissing (required)" ar="سبب التجاهل (مطلوب)" />}
                htmlFor="bulk-dismiss-reason"
                hint={
                  reasonMissing ? (
                    <Bi
                      en={`Confirm stays disabled until you write a reason (at least ${MIN_REASON_CHARS} characters). It is logged in your name for every dismissed action.`}
                      ar={`يبقى زر التأكيد معطّلًا حتى تكتب سببًا (لا يقل عن ${MIN_REASON_CHARS} أحرف)، ويُسجَّل باسمك لكل إجراء مُتجاهَل.`}
                    />
                  ) : (
                    <Bi en="The reason is logged in your name for every dismissed action." ar="يُسجَّل السبب باسمك لكل إجراء مُتجاهَل." />
                  )
                }
              >
                <Textarea
                  id="bulk-dismiss-reason"
                  value={reason}
                  maxLength={MAX_REASON_CHARS}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder={t(lang, "For example: already covered by the existing procedure.", "مثال: مغطّى بالفعل بالإجراء القائم.")}
                />
              </Field>
            )}

            {canConfirm ? (
              <div className="run-preview-confirm">
                <span>
                  <Bi
                    en={`This will ${preview.proposed_decision} ${preview.matched_action_ids.length} pending action(s). Nothing has been changed yet.`}
                    ar={`سيؤدي هذا إلى ${preview.proposed_decision === "approve" ? "اعتماد" : "تجاهل"} ${preview.matched_action_ids.length} إجراءً معلّقًا. لم يتغيّر شيء بعد.`}
                  />
                </span>
                <Button variant={preview.proposed_decision === "approve" ? "success" : "danger"} loading={confirming} disabled={reasonMissing} onClick={handleConfirm}>
                  {confirming ? (
                    // A bulk operation on dozens of actions genuinely takes
                    // several seconds (each is its own audited transition,
                    // not a single batch write). A disabled button alone read
                    // as "did this work?"; naming what is happening removes
                    // the doubt.
                    <Bi en="Applying..." ar="جارٍ التنفيذ..." />
                  ) : (
                    <Bi
                      en={`Confirm ${preview.proposed_decision}`}
                      ar={`تأكيد ${preview.proposed_decision === "approve" ? "الاعتماد" : "التجاهل"}`}
                    />
                  )}
                </Button>
              </div>
            ) : (
              preview.matched_change_ids.length > 0 && (
                <p className="run-pad-hint">
                  <Bi
                    en="Read-only: no action verb detected, or nothing pending to act on. Nothing was changed."
                    ar="للاطلاع فقط، إذ لم يُرصد فعل إجرائي أو لا يوجد إجراء معلّق لتنفيذه. لم يتغيّر شيء."
                  />
                </p>
              )
            )}
          </div>
        )}

        {result && (
          <div className="run-preview is-done">
            <div className="run-preview-head">
              <Icon icon={CircleCheck} size={18} />
              <b><Bi en="Done" ar="تم" /></b>
            </div>
            <p className="run-preview-text">
              <Bi en={`${result.updated.length} action(s) updated.`} ar={`تم تحديث ${result.updated.length} إجراءً.`} />
              {result.skipped.length > 0 && (
                <Bi
                  en={` ${result.skipped.length} skipped (already resolved by someone else).`}
                  ar={` تم تخطي ${result.skipped.length} (سُوِّيت مسبقًا من جهة أخرى).`}
                />
              )}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
