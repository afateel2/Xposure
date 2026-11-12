"""Two-way status: read the live Odoo task back into the Xposure action.

Rules:
  - The stage is recorded in Action.payload_json["erp"] on every refresh.
  - A change of stage writes an `erp_task_synced` audit row (previous and
    new stage), so the timeline shows what happened in Odoo.
  - When the task reaches Done and the action is awaiting_confirmation, the
    action moves to `done` through routes.actions._apply_transition with
    event `action_confirmed_done` and via="erp_sync". That is never silent:
    the audit row records the previous status, the Odoo task and the stage,
    and the human can undo it like any other transition.
  - Sticky undo: the close is applied only on the transition INTO done (the
    stored stage_key was not done before). If a person undoes the close, the
    next sync does not re-apply it while the Odoo task simply stays Done.
  - Connectivity problems abort the whole sync and raise ErpError; a single
    task that no longer exists is reported in `errors` and does not stop the
    others.
"""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..db.models import Action
from .client import ErpError
from .service import OdooService, build_service, now_iso

SYNC_ACTOR = "system:erp_sync"


def erp_actions(db: Session) -> list[Action]:
    """Every action that carries an Odoo task (payload_json["erp"])."""
    rows = db.scalars(select(Action).order_by(Action.id)).all()
    return [a for a in rows if isinstance(a.payload_json, dict) and a.payload_json.get("erp")]


def detach_erp(action: Action) -> None:
    """Called when a delegation is undone: the Odoo task cannot be recalled
    (undo reports it as a side effect), so the action stops pointing at it and
    keeps a record under payload_json["erp_detached"]. No commit here: the
    caller's transition commits it together with the status change."""
    payload = dict(action.payload_json or {})
    erp = payload.pop("erp", None)
    if not erp:
        return
    payload["erp_detached"] = [*payload.get("erp_detached", []), {**erp, "reason": "delegation undone"}]
    action.payload_json = payload


def refresh_action(db: Session, action: Action, service: OdooService) -> dict[str, Any]:
    """Refresh one action from Odoo. Returns a small result dict. Raises
    ErpError for connectivity/auth/api problems and for a deleted task."""
    from ..routes.actions import _apply_transition  # lazy: routes.actions imports this package

    payload = dict(action.payload_json or {})
    erp = dict(payload.get("erp") or {})
    task_id = erp.get("task_id")
    if task_id is None:
        raise ErpError("not_found", "The action has no Odoo task.", "لا توجد مهمة Odoo مرتبطة بهذا الإجراء.")

    live = service.task_state(int(task_id))
    previous_stage = erp.get("stage")
    previous_key = erp.get("stage_key")
    stage_changed = live["stage"] != previous_stage

    erp.update(
        {
            "system": "odoo",
            "task_id": live["task_id"],
            "url": live["url"],
            "stage": live["stage"],
            "stage_key": live["stage_key"],
            "assignee": live["assignee"] or erp.get("assignee"),
            "synced_at": live["synced_at"],
        }
    )
    # New dict on purpose: payload_json is a plain JSON column, not a MutableDict.
    action.payload_json = {**payload, "erp": erp}

    if stage_changed:
        audit.record(
            db,
            actor=SYNC_ACTOR,
            event="erp_task_synced",
            ref_type="action",
            ref_id=action.id,
            payload={
                "change_id": action.change_id,
                "system": "odoo",
                "task_id": live["task_id"],
                "previous_stage": previous_stage,
                "stage": live["stage"],
                "stage_key": live["stage_key"],
                "url": live["url"],
            },
            commit=False,
        )

    completed = False
    if live["stage_key"] == "done" and previous_key != "done" and action.status == "awaiting_confirmation":
        action.confirmed_at = datetime.now(timezone.utc)
        _apply_transition(
            db,
            action,
            "done",
            actor=SYNC_ACTOR,
            event="action_confirmed_done",
            via="erp_sync",
            extra={
                "system": "odoo",
                "task_id": live["task_id"],
                "erp_stage": live["stage"],
                "erp_url": live["url"],
                "reason": "The Odoo task reached Done.",
            },
        )
        completed = True
    else:
        db.commit()

    return {
        "action_id": action.id,
        "task_id": live["task_id"],
        "previous_stage": previous_stage,
        "stage": live["stage"],
        "stage_key": live["stage_key"],
        "changed": stage_changed,
        "completed": completed,
        "status": action.status,
    }


def refresh_all(db: Session, service: OdooService | None = None) -> dict[str, Any]:
    """Refresh every action that has an Odoo task. Public helper: the tasks
    list (visibility) can call this before it reads. Raises ErpError when
    Odoo is not configured, unreachable or rejects the login."""
    owns_client = service is None
    service = service or build_service()
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    try:
        for action in erp_actions(db):
            try:
                results.append(refresh_action(db, action, service))
            except ErpError as exc:
                if exc.kind != "not_found":
                    raise
                errors.append(
                    {
                        "action_id": action.id,
                        "task_id": (action.payload_json or {}).get("erp", {}).get("task_id"),
                        "message_en": exc.message_en,
                        "message_ar": exc.message_ar,
                    }
                )
    finally:
        if owns_client:
            service.client.close()
    return {
        "synced_at": now_iso(),
        "checked": len(results) + len(errors),
        "changed": [r["action_id"] for r in results if r["changed"]],
        "completed": [r["action_id"] for r in results if r["completed"]],
        "errors": errors,
        "results": results,
    }
