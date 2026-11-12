"""Delegate an Xposure action through the ERP: a real Odoo task.

Order matters and is the honesty guarantee:
  1. Talk to Odoo first (read the employee, create the task).
  2. Only if that succeeded, change the Xposure action.
If Odoo is unreachable, not configured, or refuses, an HTTPException is
raised BEFORE the action is touched: no fake success, no half-delegation.
"""

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import audit, webhooks
from ..db.models import Action
from ..routes.schemas import DelegateActionRequest
from .client import ErpError
from .service import build_service
from .tasks import build_task_text

_STATUS_BY_KIND = {
    "not_configured": 503,
    "unreachable": 503,
    "timeout": 504,
    "auth": 502,
    "api": 502,
    "not_found": 404,
}


def http_error(exc: ErpError) -> HTTPException:
    """ErpError -> HTTPException whose detail is 'English | Arabic' text."""
    return HTTPException(status_code=_STATUS_BY_KIND.get(exc.kind, 502), detail=exc.combined)


def delegate_via_odoo(db: Session, action: Action, body: DelegateActionRequest, *, actor: str) -> dict:
    from ..routes.actions import _apply_transition  # lazy: routes.actions imports this package

    try:
        service = build_service()
    except ErpError as exc:
        raise http_error(exc) from exc
    try:
        with service.client:
            employee = service.employee(int(body.employee_id))
            text = build_task_text(db, action, employee, body.note or body.message)
            task = service.create_task(
                name=text["name"],
                description_html=text["description_html"],
                employee=employee,
                due_date=text["due_date"],
                important=text["important"],
            )
    except ErpError as exc:
        raise http_error(exc) from exc

    now = datetime.now(timezone.utc)
    erp = {
        "system": "odoo",
        "task_id": task["task_id"],
        "url": task["url"],
        "stage": task["stage"],
        "stage_key": task["stage_key"],
        "assignee": task["assignee"],
        "synced_at": task["synced_at"],
    }
    # Fresh dict: payload_json is a plain JSON column, not a MutableDict.
    action.payload_json = {**(action.payload_json or {}), "erp": erp}
    action.assignee_name = employee["name"]
    action.assignee_contact = employee.get("work_email")
    action.delegated_at = now

    audit.record(
        db,
        actor=actor,
        event="erp_task_created",
        ref_type="action",
        ref_id=action.id,
        payload={
            "change_id": action.change_id,
            "system": "odoo",
            "task_id": task["task_id"],
            "url": task["url"],
            "stage": task["stage"],
            "employee": {
                "id": employee["id"],
                "name": employee["name"],
                "job_title": employee.get("job_title"),
                "work_email": employee.get("work_email"),
                "has_user": bool(employee.get("user_id")),
            },
            "task_name": text["name"],
        },
        commit=False,
    )
    # The Odoo task IS the notification for this channel. It is recorded in
    # the same "notification" slot the email channel uses, so the undo and
    # the sent-notifications list report it as a side effect that cannot be
    # taken back.
    notification = {"sent": True, "channel": "odoo", "target": task["url"], "task_id": task["task_id"]}
    _apply_transition(
        db,
        action,
        "awaiting_confirmation",
        actor=actor,
        event="action_delegated",
        via="erp",
        extra={
            "assignee_name": employee["name"],
            "assignee_contact": employee.get("work_email"),
            "message": body.note or body.message,
            "notification": notification,
            "erp_task_id": task["task_id"],
        },
    )

    webhook_result = webhooks.send_webhook(
        "action.delegated",
        {"action_id": action.id, "change_id": action.change_id, "type": action.type, "assignee_name": employee["name"]},
    )
    audit.record(
        db, actor="api:webhooks", event="webhook_action_delegated", ref_type="action", ref_id=action.id,
        payload=webhook_result,
    )
    return {
        "id": action.id,
        "status": action.status,
        "assignee_name": action.assignee_name,
        "assignee_contact": action.assignee_contact,
        "erp": erp,
    }
