"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Bi } from "@/components/Bi";
import { Button, Checkbox, Icon, useToast } from "@/components/ui";
import { t, useLang } from "@/lib/lang";
import type { ReviewQueue } from "@/lib/review-queue";

const AUTO_ADVANCE_KEY = "xposure_queue_autoadvance";
const AUTO_ADVANCE_DELAY_MS = 1600;

/** Keys must not fire while someone types a reason or has a dialog open. */
function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
}

/**
 * The review queue bar, pinned to the bottom of a change's page.
 *
 * Review is sequential work, and going back to the list after every change
 * makes the reviewer find their place again. This bar shows where the change
 * sits in the queue, how many actions on it are decided, and takes you to the
 * neighbouring change (buttons, or j for next and k for previous). Auto-advance
 * is off by default on purpose: after "Let the agent handle it" the reviewer
 * needs to read the file diff and may want to undo, so the page must not move
 * on its own unless asked to.
 */
export function QueueBar({
  queue, changeId, pending, total,
}: {
  queue: ReviewQueue;
  changeId: number;
  /** Actions on this change still waiting for a decision. */
  pending: number;
  /** All actions on this change. */
  total: number;
}) {
  const lang = useLang();
  const router = useRouter();
  const toast = useToast();
  const [autoAdvance, setAutoAdvance] = useState(false);
  const prevPending = useRef<number | null>(null);
  const { markResolved, nextId, prevId } = queue;

  useEffect(() => {
    try {
      setAutoAdvance(localStorage.getItem(AUTO_ADVANCE_KEY) === "1");
    } catch {
      /* storage can be blocked: the default (off) is fine */
    }
  }, []);

  function toggleAutoAdvance(value: boolean) {
    setAutoAdvance(value);
    try {
      localStorage.setItem(AUTO_ADVANCE_KEY, value ? "1" : "0");
    } catch {
      /* best effort */
    }
  }

  // Tell the queue when this change has nothing left to decide (and when an undo reopens it).
  useEffect(() => {
    markResolved(changeId, total > 0 && pending === 0);
  }, [changeId, pending, total, markResolved]);

  // j / k move through the queue. Ignored while typing, in a dialog, or with a modifier held.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || isTyping(e.target)) return;
      if (document.querySelector("dialog[open]")) return;
      if (e.key === "j" && nextId !== null) router.push(`/changes/${nextId}`);
      if (e.key === "k" && prevId !== null) router.push(`/changes/${prevId}`);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [router, nextId, prevId]);

  // Optional auto-advance: only when the last pending action was decided during this visit.
  useEffect(() => {
    const before = prevPending.current;
    prevPending.current = pending;
    if (!autoAdvance || nextId === null || before === null || before === 0 || pending !== 0) return;
    toast.info(<Bi en="All actions on this change are decided. Moving to the next one..." ar="حُسمت كل الإجراءات في هذا التغيير. الانتقال إلى التالي..." />);
    const timer = window.setTimeout(() => router.push(`/changes/${nextId}`), AUTO_ADVANCE_DELAY_MS);
    return () => window.clearTimeout(timer); // an undo (pending > 0 again) cancels the move
  }, [pending, autoAdvance, nextId, router, toast]);

  if (queue.status === "error") return null;

  const decided = total - pending;
  const percent = total > 0 ? Math.round((decided / total) * 100) : 0;
  const allDecided = total > 0 && pending === 0;

  return (
    <div className="chg-queue" role="region" aria-label={t(lang, "Review queue", "طابور المراجعة")}>
      <div className="chg-queue-nav">
        {prevId !== null ? (
          <Button variant="secondary" size="sm" href={`/changes/${prevId}`} icon={<Icon icon={ChevronRight} size={16} flipRtl />} title={t(lang, "Previous change (k)", "التغيير السابق (k)")}>
            <Bi en="Previous" ar="السابق" />
          </Button>
        ) : (
          <span className="chg-queue-disabled"><Icon icon={ChevronRight} size={16} flipRtl /><Bi en="Previous" ar="السابق" /></span>
        )}
        <span className="chg-queue-where" aria-live="polite">
          {queue.status === "loading" ? (
            <Bi en="Loading the queue..." ar="جارٍ تحميل الطابور..." />
          ) : queue.position !== null ? (
            <Bi
              en={<>Change <b className="tabular">{queue.position}</b> of <b className="tabular">{queue.total}</b> needing a decision</>}
              ar={<>التغيير <b className="tabular">{queue.position}</b> من <b className="tabular">{queue.total}</b> بحاجة إلى قرار</>}
            />
          ) : (
            <Bi en="Not in the review queue (already decided)" ar="ليس في طابور المراجعة (حُسم بالفعل)" />
          )}
        </span>
        {nextId !== null ? (
          <Button
            variant={allDecided ? "primary" : "secondary"}
            size="sm"
            href={`/changes/${nextId}`}
            icon={<Icon icon={ChevronLeft} size={16} flipRtl />}
            title={t(lang, "Next change (j)", "التغيير التالي (j)")}
          >
            <Bi en="Next change" ar="التغيير التالي" />
          </Button>
        ) : (
          <span className="chg-queue-disabled"><Bi en="Next change" ar="التغيير التالي" /><Icon icon={ChevronLeft} size={16} flipRtl /></span>
        )}
      </div>

      <div className="chg-queue-progress">
        {total > 0 ? (
          <>
            <span className="chg-queue-count">
              <Bi
                en={<><b className="tabular">{decided}</b> of <b className="tabular">{total}</b> actions on this change decided</>}
                ar={<>حُسم <b className="tabular">{decided}</b> من <b className="tabular">{total}</b> إجراءً في هذا التغيير</>}
              />
            </span>
            <span className="chg-queue-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}>
              <i style={{ inlineSize: `${percent}%` }} />
            </span>
          </>
        ) : (
          <span className="chg-queue-count"><Bi en="This change has no actions to decide." ar="لا توجد إجراءات للبتّ فيها في هذا التغيير." /></span>
        )}
        {queue.status === "ready" && (
          <span className="chg-queue-left">
            <Bi en={<><b className="tabular">{queue.remaining}</b> still need a decision</>} ar={<><b className="tabular">{queue.remaining}</b> ما زالت بحاجة إلى قرار</>} />
          </span>
        )}
      </div>

      <div className="chg-queue-opts">
        <Checkbox checked={autoAdvance} onChange={(e) => toggleAutoAdvance(e.target.checked)}>
          <Bi en="Move on automatically after the last decision" ar="الانتقال تلقائيًا بعد آخر قرار" />
        </Checkbox>
        <span className="chg-queue-keys" aria-hidden="true"><kbd>k</kbd> <Bi en="previous" ar="السابق" /> · <kbd>j</kbd> <Bi en="next" ar="التالي" /></span>
      </div>
    </div>
  );
}
