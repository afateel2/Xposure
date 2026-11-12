"""
POST /actions/{id}/approve and /dismiss — the human-review decision path
for M7's UI.

This does NOT resume a LangGraph thread. agent/graph.py's
human_review_node interrupts only for the actions ITS OWN run created,
and its docstring is explicit that this is deliberate: "The global inbox
is M7's UI, which approves/dismisses through the API rather than by
resuming a graph thread." So this endpoint does exactly what
human_review_node's resume branch does (set Action.status, write an
audit_log row, in one transaction) but against any pending action from
any run, which is what a real reviewer's inbox needs — they do not care
which agent run produced an action.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, notify, webhooks
from ..auth import require_user
from ..company import effects as company_effects
from ..db.models import Action, AppUser, AuditLog
from ..db.session import get_db
from .schemas import BulkActionRequest, BulkActionResult, DelegateActionRequest, DismissRequest, UndoResult

router = APIRouter(tags=["actions"])

# A dismissal without a stated reason leaves the audit log answering only
# "who", never "why". The UI will not enable the button without one; this is
# the same rule enforced where it cannot be bypassed.
MIN_REASON_CHARS = 3
MAX_REASON_CHARS = 500


def _clean_reason(reason: str | None) -> str:
    text = " ".join((reason or "").split())
    if len(text) < MIN_REASON_CHARS:
        raise HTTPException(
            status_code=422,
            detail=f"A written reason is required to dismiss an action (at least {MIN_REASON_CHARS} characters).",
        )
    return text[:MAX_REASON_CHARS]


def _remember_dismiss_reason(action: Action, reason: str) -> None:
    # Fresh dict: payload_json is a plain JSON column, not a MutableDict.
    action.payload_json = {**(action.payload_json or {}), "dismiss_reason": reason}

# Every audit event that _apply_transition can produce — the only events
# whose payload is guaranteed to carry "previous_status". undo() reads the
# most recent one of these for a given action to know what to revert to.
TRANSITION_EVENTS = (
    "action_approved", "action_dismissed", "action_delegated",
    "action_confirmed_done", "action_auto_executed", "action_status_reverted",
)

# event -> human-readable label, for the two "we sent something real"
# audit rows undo() checks when reporting what it can't take back.
_DELIVERY_EVENTS = {
    "webhook_action_approved": "webhook: action.approved",
    "webhook_action_delegated": "webhook: action.delegated",
}


def _apply_transition(
    db: Session,
    action: Action,
    new_status: str,
    *,
    actor: str,
    event: str,
    via: str,
    extra: dict | None = None,
) -> Action:
    """Every status-mutating write in this file (and human_review_node's
    resume path in agent/graph.py) goes through this shape: capture the
    status BEFORE overwriting it, and always record it. Undo (added in a
    later pass) reads `previous_status` back off this exact payload — this
    is the one place that fact gets written, so it can't drift between
    call sites the way it would if each endpoint built its own payload."""
    previous = action.status
    action.status = new_status
    if new_status == "dismissed" and extra and extra.get("reason"):
        # Must happen before audit.record(), which commits: the reason is
        # saved in the same transaction as the status change and its audit row.
        _remember_dismiss_reason(action, str(extra["reason"]))
    audit.record(
        db,
        actor=actor,
        event=event,
        ref_type="action",
        ref_id=action.id,
        payload={
            "change_id": action.change_id,
            "type": action.type,
            "previous_status": previous,
            "via": via,
            **(extra or {}),
        },
    )
    return action


def _resolve(db: Session, action_id: int, new_status: str, *, actor: str, extra: dict | None = None) -> Action:
    action = db.get(Action, action_id)
    if action is None:
        raise HTTPException(status_code=404, detail=f"No action with id {action_id}.")
    if action.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Action {action_id} is already {action.status!r}, not pending: refusing to change it again.",
        )
    return _apply_transition(
        db,
        action,
        new_status,
        # A real signed-in reviewer's identity (app/auth.py), not the old
        # literal "user:web" every actor shared before auth existed.
        # agent/graph.py's human_review_node keeps its own CLI-path literal
        # (that path has no HTTP request to carry a session on).
        actor=actor,
        event=f"action_{new_status}",
        via="api",
        extra=extra,
    )


def _send_approve_webhook(db: Session, action: Action) -> None:
    # M8: best-effort notification only, per the takeoff prompt's named
    # webhook events (change.detected/impact.computed/action.approved) —
    # dismiss has no corresponding event. Never blocks or fails the
    # approval itself; see app/webhooks.py's module docstring.
    result = webhooks.send_webhook(
        "action.approved",
        {"action_id": action.id, "change_id": action.change_id, "type": action.type, "level": action.level},
    )
    audit.record(
        db,
        actor="api:webhooks",
        event="webhook_action_approved",
        ref_type="action",
        ref_id=action.id,
        payload=result,
    )


@router.post("/actions/{action_id}/approve")
def approve_action(action_id: int, db: Session = Depends(get_db), user: AppUser = Depends(require_user)):
    action = _resolve(db, action_id, "approved", actor=user.actor())
    _send_approve_webhook(db, action)
    # Single approval only (bulk approve stays decision-only): let the agent
    # carry out the action on the mapped company file, if there is one.
    outcome = company_effects.apply_after_approve(db, action)
    return {"id": action.id, "status": action.status, **outcome}


@router.post("/actions/{action_id}/dismiss")
def dismiss_action(
    action_id: int,
    body: DismissRequest | None = None,
    db: Session = Depends(get_db),
    user: AppUser = Depends(require_user),
):
    # Validate the reason before touching the action, so a missing reason
    # leaves it pending (and the audit log unchanged).
    reason = _clean_reason(body.reason if body else None)
    action = _resolve(db, action_id, "dismissed", actor=user.actor(), extra={"reason": reason})
    return {"id": action.id, "status": action.status, "reason": reason}


@router.post("/actions/{action_id}/delegate")
def delegate_action(
    action_id: int, body: DelegateActionRequest, db: Session = Depends(get_db), user: AppUser = Depends(require_user)
):
    action = db.get(Action, action_id)
    if action is None:
        raise HTTPException(status_code=404, detail=f"No action with id {action_id}.")
    if action.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Action {action_id} is already {action.status!r}, not pending: refusing to delegate it.",
        )

    if body.channel == "odoo":
        # Real ERP task first; the action is only touched if Odoo accepted it.
        from ..erp.delegate import delegate_via_odoo  # lazy: erp.* imports this module

        return delegate_via_odoo(db, action, body, actor=user.actor())

    now = datetime.now(timezone.utc)
    action.assignee_name = body.assignee_name
    action.assignee_contact = body.assignee_contact
    action.delegated_at = now

    notify_result = notify.send_notification(
        channel=None,  # use whatever settings.notification_channel is configured, if any
        target=body.assignee_contact,
        subject=f"Xposure: {action.type} needs your attention",
        message=body.message or f"You've been assigned action #{action.id} ({action.type}).",
        payload={"action_id": action.id, "change_id": action.change_id, "type": action.type},
    )
    _apply_transition(
        db,
        action,
        "awaiting_confirmation",
        actor=user.actor(),
        event="action_delegated",
        via="api",
        extra={
            "assignee_name": body.assignee_name,
            "assignee_contact": body.assignee_contact,
            "message": body.message,
            "notification": notify_result,
        },
    )

    # Parity with approve's webhook — same best-effort, never-blocking shape.
    webhook_result = webhooks.send_webhook(
        "action.delegated",
        {"action_id": action.id, "change_id": action.change_id, "type": action.type, "assignee_name": body.assignee_name},
    )
    audit.record(
        db, actor="api:webhooks", event="webhook_action_delegated", ref_type="action", ref_id=action.id,
        payload=webhook_result,
    )
    return {"id": action.id, "status": action.status, "assignee_name": action.assignee_name, "assignee_contact": action.assignee_contact}


@router.get("/notifications/sent")
def list_sent_notifications(db: Session = Depends(get_db), limit: int = 50):
    """Same shape and purpose as GET /webhooks/received (routes/webhooks.py)
    for the outbound side: what did delegating an action actually try to
    send, and did it go anywhere. No dedicated table — every delegate()
    call already writes the notify.send_notification() result into its
    action_delegated audit row's payload; this just lists those rows,
    same "the audit log already models this" reasoning."""
    rows = db.scalars(
        select(AuditLog).where(AuditLog.event == "action_delegated").order_by(AuditLog.id.desc()).limit(limit)
    )
    return [
        {
            "id": r.id,
            "ts": r.ts,
            "action_id": r.ref_id,
            "assignee_name": (r.payload_json or {}).get("assignee_name"),
            "notification": (r.payload_json or {}).get("notification"),
        }
        for r in rows
    ]


@router.post("/actions/{action_id}/confirm")
def confirm_action(action_id: int, db: Session = Depends(get_db), user: AppUser = Depends(require_user)):
    action = db.get(Action, action_id)
    if action is None:
        raise HTTPException(status_code=404, detail=f"No action with id {action_id}.")
    if action.status != "awaiting_confirmation":
        raise HTTPException(
            status_code=409,
            detail=f"Action {action_id} is {action.status!r}, not awaiting_confirmation: nothing to confirm.",
        )
    action.confirmed_at = datetime.now(timezone.utc)
    # Distinct from auto_execute's "done" on purpose: this close was a
    # human self-attesting that a delegated task was completed, not the
    # agent verifying anything — the audit trail must not blur the two.
    _apply_transition(db, action, "done", actor=user.actor(), event="action_confirmed_done", via="manual_confirmation")
    return {"id": action.id, "status": action.status}


def _side_effects_not_reversed(db: Session, action_id: int) -> list[str]:
    effects: list[str] = []
    rows = db.scalars(
        select(AuditLog).where(AuditLog.ref_type == "action", AuditLog.ref_id == action_id)
    ).all()
    for row in rows:
        label = _DELIVERY_EVENTS.get(row.event)
        if label and (row.payload_json or {}).get("sent") is True:
            effects.append(label)
        if row.event == "action_delegated":
            notification = (row.payload_json or {}).get("notification") or {}
            if notification.get("sent") is True:
                effects.append(f"notification: {notification.get('channel', 'unknown channel')}")
    return effects


@router.post("/actions/{action_id}/undo", response_model=UndoResult)
def undo_action(action_id: int, db: Session = Depends(get_db), user: AppUser = Depends(require_user)):
    """Single-level toggle against the most recently recorded transition —
    not an arbitrary-depth history stack (see docs/PLAN.md). Calling this
    twice in a row toggles back to the pre-undo state, i.e. redo is "call
    undo again". Reverts our own status record only: a webhook or
    notification already fired for the transition being undone cannot be
    recalled, and side_effects_not_reversed says so explicitly rather than
    implying a full rollback that did not happen."""
    action = db.get(Action, action_id)
    if action is None:
        raise HTTPException(status_code=404, detail=f"No action with id {action_id}.")

    last_transition = db.scalar(
        select(AuditLog)
        .where(AuditLog.ref_type == "action", AuditLog.ref_id == action_id, AuditLog.event.in_(TRANSITION_EVENTS))
        .order_by(AuditLog.id.desc())
    )
    if last_transition is None:
        raise HTTPException(status_code=409, detail=f"Action {action_id} has no recorded transition to undo.")

    previous_status = (last_transition.payload_json or {}).get("previous_status")
    if previous_status is None:
        raise HTTPException(
            status_code=409,
            detail=f"Action {action_id}'s last transition (event={last_transition.event!r}) has no "
            f"previous_status recorded: cannot undo it safely.",
        )

    side_effects = _side_effects_not_reversed(db, action_id)
    # A file edit is reversible, so it is reverted (or, if a newer version of
    # the file exists, honestly reported as kept), not listed as unreversed.
    status_before_undo = action.status
    effect_reverted, effect_notes = company_effects.revert_before_undo(db, action, previous_status, actor=user.actor())
    side_effects = [*side_effects, *effect_notes]
    if last_transition.event == "action_delegated":
        # Undoing the delegation itself (not just a later confirm) must
        # clear who it was delegated to — otherwise a plain "pending"
        # action would still show a stale "Assigned to <name>" from a
        # delegation that no longer exists. Found live: delegate, then
        # undo, left exactly this stale state on a real action before
        # this check was added. Undoing a *confirm* (previous_status ==
        # "awaiting_confirmation") must NOT clear these — the action is
        # still genuinely delegated, just not confirmed done yet.
        action.assignee_name = None
        action.assignee_contact = None
        action.delegated_at = None
        # An Odoo task made by this delegation still exists in Odoo (it is
        # listed in side_effects above), but the action must stop pointing at it.
        from ..erp.sync import detach_erp  # lazy: erp.* imports this module

        detach_erp(action)
    _apply_transition(
        db, action, previous_status, actor=user.actor(), event="action_status_reverted", via="undo",
        extra={"reverted_event": last_transition.event, "side_effects_not_reversed": side_effects},
    )
    effect_reapplied = company_effects.reapply_after_undo(db, action, status_before_undo)
    return UndoResult(
        id=action.id, status=action.status, side_effects_not_reversed=side_effects,
        effect_reverted=effect_reverted, effect_reapplied=effect_reapplied,
    )


@router.post("/actions/bulk", response_model=BulkActionResult)
def bulk_action(body: BulkActionRequest, db: Session = Depends(get_db), user: AppUser = Depends(require_user)):
    """Deliberately diverges from the single-action endpoints' hard-409:
    partial success, reporting a skip reason per stale id, rather than
    failing the whole batch because one row changed since the caller last
    looked. A 20-item bulk-approve should not be undone by one row that's
    already approved."""
    new_status = "approved" if body.decision == "approve" else "dismissed"
    event = f"action_{new_status}"
    updated: list[int] = []
    skipped: list[dict] = []
    # Same rule as the single dismissal: no reason, no dismissal (nothing is
    # changed, so a rejected request is safe to retry with a reason).
    reason = _clean_reason(body.reason) if body.decision == "dismiss" else None

    for action_id in body.action_ids:
        action = db.get(Action, action_id)
        if action is None:
            skipped.append({"id": action_id, "reason": "not found"})
            continue
        if action.status != "pending":
            skipped.append({"id": action_id, "reason": f"not pending (status={action.status})"})
            continue
        _apply_transition(
            db, action, new_status, actor=user.actor(), event=event, via="bulk",
            extra={"reason": reason} if reason else None,
        )
        if body.decision == "approve":
            _send_approve_webhook(db, action)
        updated.append(action_id)

    audit.record(
        db, actor=user.actor(), event="bulk_action_applied",
        payload={"decision": body.decision, "updated": updated, "skipped": skipped, **({"reason": reason} if reason else {})},
    )
    return BulkActionResult(updated=updated, skipped=skipped)
