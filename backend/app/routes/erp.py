"""ERP (Odoo) endpoints.

  GET  /erp/status          honest connectivity report (never errors)
  GET  /erp/employees       Odoo employees, for the delegate picker
  POST /erp/tasks           create a task for an action (delegate uses the
                            same code path via channel="odoo")
  GET  /erp/tasks           actions that have an Odoo task (refresh=true
                            re-reads Odoo and applies Done -> action done)
  GET  /erp/tasks/{id}      live state of one Odoo task (read only)
  POST /erp/sync            refresh every action that has an Odoo task

Failures are loud: Odoo down or not configured gives a 5xx whose `detail`
is 'English | Arabic' text, never an empty list or a fake success.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import require_user
from ..db.models import Action, AppUser
from ..db.session import get_db
from ..erp import service as erp_service
from ..erp import sync as erp_sync
from ..erp.client import ErpError
from ..erp.delegate import delegate_via_odoo, http_error
from .schemas import DelegateActionRequest

router = APIRouter(tags=["erp"])


class CreateTaskRequest(BaseModel):
    action_id: int
    employee_id: int
    note: str | None = None


@router.get("/erp/status")
def erp_status() -> dict[str, Any]:
    return erp_service.status()


@router.get("/erp/employees")
def erp_employees() -> list[dict[str, Any]]:
    try:
        service = erp_service.build_service()
        with service.client:
            return service.employees()
    except ErpError as exc:
        raise http_error(exc) from exc


@router.post("/erp/tasks")
def create_erp_task(
    body: CreateTaskRequest, db: Session = Depends(get_db), user: AppUser = Depends(require_user)
) -> dict[str, Any]:
    """Create the Odoo task for an action and delegate it (status becomes
    awaiting_confirmation), exactly like POST /actions/{id}/delegate with
    channel=odoo. There is deliberately one code path."""
    action = db.get(Action, body.action_id)
    if action is None:
        raise HTTPException(status_code=404, detail=f"No action with id {body.action_id}.")
    if action.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Action {body.action_id} is already {action.status!r}, not pending: refusing to create a task.",
        )
    request = DelegateActionRequest(channel="odoo", employee_id=body.employee_id, note=body.note)
    return delegate_via_odoo(db, action, request, actor=user.actor())


def _linked_actions(db: Session) -> list[Action]:
    return erp_sync.erp_actions(db)


@router.get("/erp/tasks")
def list_erp_tasks(
    refresh: bool = Query(True, description="Re-read every task from Odoo first (applies Done to the action)"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    sync_result: dict[str, Any] | None = None
    if refresh:
        try:
            sync_result = erp_sync.refresh_all(db)
        except ErpError as exc:
            raise http_error(exc) from exc
    items = []
    for action in _linked_actions(db):
        erp = (action.payload_json or {}).get("erp") or {}
        items.append(
            {
                "action_id": action.id,
                "change_id": action.change_id,
                "action_status": action.status,
                "task_id": erp.get("task_id"),
                "url": erp.get("url"),
                "stage": erp.get("stage"),
                "stage_key": erp.get("stage_key"),
                "assignee": erp.get("assignee"),
                "synced_at": erp.get("synced_at"),
            }
        )
    return {"refreshed": refresh, "items": items, "sync": sync_result}


@router.get("/erp/tasks/{task_id}")
def get_erp_task(task_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Live state straight from Odoo. Read only: it does not change the
    action. (POST /erp/sync or GET /erp/tasks does.)"""
    try:
        service = erp_service.build_service()
        with service.client:
            state = service.task_state(task_id)
    except ErpError as exc:
        raise http_error(exc) from exc
    if not state.get("assignee"):
        for action in _linked_actions(db):
            erp = (action.payload_json or {}).get("erp") or {}
            if erp.get("task_id") == task_id:
                state["assignee"] = erp.get("assignee") or action.assignee_name
                break
    return {
        "task_id": state["task_id"],
        "url": state["url"],
        "stage": state["stage"],
        "stage_key": state["stage_key"],
        "assignee": state["assignee"],
        "synced_at": state["synced_at"],
    }


@router.post("/erp/sync")
def sync_erp(db: Session = Depends(get_db), user: AppUser = Depends(require_user)) -> dict[str, Any]:
    try:
        return erp_sync.refresh_all(db)
    except ErpError as exc:
        raise http_error(exc) from exc
