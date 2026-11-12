"""
GET /agent/state: what is the agent doing right now?

Derived only from audit_log (plus the pending-action count), so it works with
or without the demo runner module. Events understood:

  demo runner   scan_requested, stage_started, stage_completed, scan_completed, scan_failed
  agent loop    sources_checked ... run_paused_for_human_review, human_review_*,
                run_delivered, run_failed, resume_failed
  reset         demo_reset (state returns to idle; older history is ignored)

The NEWEST lifecycle event decides:
  scan_failed | run_failed | resume_failed                       -> failed
  scan_completed | run_delivered | run_paused_for_human_review
    | human_review_applied                                       -> awaiting_review when
                                                                    pending actions exist, else idle
  demo_reset, or no lifecycle event at all                       -> idle (or awaiting_review if
                                                                    pending actions exist)
  anything else (a run started and has not finished)             -> scanning
A run that has shown no progress for STALL_SECONDS is reported as failed
("stalled") rather than as scanning forever: a killed process leaves no
run_failed row, and pretending it is still working would be dishonest.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import Action, AuditLog
from . import labels as L
from .events import Ev, _stage
from .labels import ar_count, isolate, trunc
from .timeutil import as_utc, utc_now
from .window import RESET_EVENT, get_window

STALL_SECONDS = 30 * 60

FAILED_EVENTS = frozenset({"scan_failed", "run_failed", "resume_failed"})
DONE_EVENTS = frozenset({"scan_completed", "run_delivered", "human_review_applied"})
PAUSED_EVENTS = frozenset({"run_paused_for_human_review"})
TERMINAL_EVENTS = FAILED_EVENTS | DONE_EVENTS | PAUSED_EVENTS

LIFECYCLE_EVENTS = tuple(sorted(TERMINAL_EVENTS | {
    RESET_EVENT, "scan_requested", "stage_started", "stage_completed", "sources_checked", "source_ingested",
    "baseline_ingested", "ingest_new_completed", "versions_diffed", "diff_completed",
    "impact_node_completed", "prioritize_completed", "apply_policy_completed", "auto_execute_completed",
    "human_review_skipped",
}))

_SCAN_TS_EVENTS = ("sources_checked", "scan_completed")


def _iso(value: datetime | None) -> datetime | None:
    return as_utc(value)


def _last_run(rows: list[Ev]) -> tuple[str | None, dict[str, Any] | None, datetime | None]:
    """(status, summary, ts) of the newest FINISHED run marker, newest-first rows."""
    for ev in rows:
        if ev.event in FAILED_EVENTS:
            error = trunc(ev.p.get("error") or ev.p.get("reason") or ev.p.get("message") or "", 300)
            return "failed", {"run_id": ev.run_id or None, "error": error, "stage": ev.p.get("stage")}, ev.ts
        if ev.event in ("run_delivered", "scan_completed"):
            return "completed", dict(ev.p), ev.ts
        if ev.event in PAUSED_EVENTS:
            ids = ev.p.get("awaiting_action_ids")
            return "awaiting_review", {"run_id": ev.run_id or None, "awaiting_count": len(ids) if isinstance(ids, list) else None}, ev.ts
        if ev.event == "human_review_applied":
            return "completed", dict(ev.p), ev.ts
    return None, None, None


def _current_stage(rows: list[Ev], run_start_id: int) -> dict[str, str] | None:
    """Newest stage_started (in the current run) that has no stage_completed yet."""
    started = [e for e in rows if e.event == "stage_started" and e.id >= run_start_id]
    if not started:
        return None
    newest = started[0]
    key = _stage(newest.p)[0]
    done = any(e.event == "stage_completed" and _stage(e.p)[0] == key and e.id > newest.id for e in rows)
    if done:
        return None
    _, en, ar = _stage(newest.p)
    return {"key": key, "label_en": en, "label_ar": ar}


def compute_agent_state(db: Session, now: datetime | None = None) -> dict[str, Any]:
    now = now or utc_now().replace(tzinfo=None)  # naive UTC, like the stored timestamps
    window = get_window(db, since_reset=True)

    stmt = select(AuditLog).where(AuditLog.event.in_(LIFECYCLE_EVENTS))
    if window.active and window.reset_id is not None:
        stmt = stmt.where(AuditLog.id >= window.reset_id)
    rows = [Ev.from_row(r) for r in db.scalars(stmt.order_by(AuditLog.id.desc()).limit(600))]  # newest first

    pending = db.scalar(select(func.count()).select_from(Action).where(Action.status == "pending")) or 0
    awaiting_conf = db.scalar(select(func.count()).select_from(Action).where(Action.status == "awaiting_confirmation")) or 0
    pending_changes = db.scalar(
        select(func.count(func.distinct(Action.change_id))).where(Action.status == "pending")
    ) or 0

    newest = rows[0] if rows else None
    last_scan = next((e for e in rows if e.event in _SCAN_TS_EVENTS), None)
    last_status, last_summary, last_run_ts = _last_run(rows)

    state, since, stalled, run_id, stage = "idle", None, False, None, None
    if newest is None or newest.event == RESET_EVENT:
        state = "idle"
        since = newest.ts if newest else None
    elif newest.event in FAILED_EVENTS:
        state, since, run_id = "failed", newest.ts, newest.run_id or None
    elif newest.event in DONE_EVENTS | PAUSED_EVENTS:
        state, since, run_id = "idle", newest.ts, newest.run_id or None
    else:
        # A run started and has not reached a terminal event.
        last_terminal_id = next((e.id for e in rows if e.event in TERMINAL_EVENTS or e.event == RESET_EVENT), 0)
        starts = [e for e in rows if e.id > last_terminal_id and e.event in ("scan_requested", "sources_checked")]
        start = starts[-1] if starts else newest
        run_id = newest.run_id or start.run_id or None
        # Progress is any audit row since the run started (impact/priority/
        # action rows are written continuously while the pipeline works).
        last_activity = db.scalar(select(func.max(AuditLog.ts)).where(AuditLog.id >= start.id)) or newest.ts
        if (now - last_activity).total_seconds() > STALL_SECONDS:
            state, since, stalled = "failed", last_activity, True
        else:
            state, since = "scanning", start.ts
            stage = _current_stage(rows, start.id)

    if state == "idle" and pending > 0:
        state = "awaiting_review"

    if state == "idle":
        msg_en, msg_ar = "The agent is idle. No scan is running.", "الوكيل في وضع الخمول ولا يوجد فحص قيد التنفيذ."
    elif state == "scanning":
        if stage:
            msg_en, msg_ar = f"Scanning now: {stage['label_en']}.", f"الفحص جارٍ الآن: {stage['label_ar']}."
        else:
            msg_en, msg_ar = "Scanning now. The pipeline is running.", "الفحص جارٍ الآن وخط المعالجة قيد التشغيل."
    elif state == "awaiting_review":
        msg_en = f"{pending} {'action is' if pending == 1 else 'actions are'} waiting for your decision."
        msg_ar = f"بانتظار قرارك بشأن {ar_count(pending, L.ACTION)}."
    else:
        err = (last_summary or {}).get("error") or ""
        if stalled:
            msg_en = "The last run stopped without finishing (no progress was recorded for 30 minutes)."
            msg_ar = "توقف آخر تشغيل دون أن يكتمل (لم يُسجَّل أي تقدم لمدة 30 دقيقة)."
        else:
            msg_en = f"The last run failed: {err}" if err else "The last run failed."
            msg_ar = f"فشل آخر تشغيل: {isolate(err)}" if err else "فشل آخر تشغيل."

    return {
        "state": state,
        "since": _iso(since),
        "awaiting_count": int(pending),
        "awaiting_changes": int(pending_changes),
        "awaiting_confirmation_count": int(awaiting_conf),
        "last_scan_at": _iso(last_scan.ts) if last_scan else None,
        "last_run_status": last_status,
        "last_run_summary": last_summary,
        "last_run_at": _iso(last_run_ts),
        "run_id": run_id,
        "stage": stage,
        "stalled": stalled,
        "message_en": msg_en,
        "message_ar": msg_ar,
    }
