"""
GET /tasks: actions across all changes for the Tasks page.

Definitions (shared with /overview): a TASK is an action delegated to a person
or the ERP and not yet confirmed done (status awaiting_confirmation). This
endpoint lists ACTIONS of every status so the page can offer tabs (open,
pending review, done, ...); `status=open` selects the tasks proper.

Read-only. Sorting: unresolved-and-overdue first, then due date (no due date
last), then id.
"""

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import Action, AuditLog, Change, OrgNode, Regulation, Regulator
from ..db.session import get_db
from ..visibility import labels as L
from ..visibility.labels import clean
from ..visibility.priority_index import load_priority_index
from ..visibility.schemas import TasksOut
from ..visibility.timeutil import as_utc

router = APIRouter(tags=["visibility"])

DUE_SOON_DAYS = 5
FAR_FUTURE = date(9999, 12, 31)


def _parse_status(value: str | None) -> list[str] | None:
    """`all`/empty -> no filter; `open` -> awaiting_confirmation; `unresolved`
    -> pending + awaiting_confirmation; otherwise a comma list of statuses."""
    if not value or value.strip().lower() == "all":
        return None
    out: list[str] = []
    for token in (t.strip().lower() for t in value.split(",") if t.strip()):
        if token == "open":
            out.append("awaiting_confirmation")
        elif token == "unresolved":
            out += list(L.OPEN_STATUSES)
        elif token in L.ACTION_STATUSES:
            out.append(token)
        else:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown status {token!r}: use all, open, unresolved or any of {', '.join(L.ACTION_STATUSES)}.",
            )
    return out


def _effect_view(effect: Any, include_diff: bool) -> dict[str, Any] | None:
    if not isinstance(effect, dict):
        return None
    if include_diff:
        return dict(effect)
    view = {k: v for k, v in effect.items() if k != "diff_unified"}
    if "diff_unified" in effect:
        view["has_diff"] = True
    return view


def _erp_view(erp: Any) -> dict[str, Any] | None:
    if not isinstance(erp, dict):
        return None
    return {k: erp.get(k) for k in ("system", "task_id", "url", "stage", "assignee", "synced_at")}


@router.get("/tasks", response_model=TasksOut)
def list_tasks(
    status: str | None = Query(None, description="all (default) | open | unresolved | one or more of pending, awaiting_confirmation, approved, done, dismissed (comma separated)."),
    assigned: bool | None = Query(None, description="true: only actions with an assignee; false: only unassigned."),
    change_id: int | None = Query(None, description="Only actions of this change."),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    include_effect_diff: bool = Query(False, description="Include the full unified diff of agent file edits (heavy)."),
    db: Session = Depends(get_db),
):
    wanted = _parse_status(status)
    today = date.today()

    changes = list(db.scalars(select(Change)))
    change_by_id = {c.id: c for c in changes}
    prio = load_priority_index(db, changes)
    reg_map = {
        regulation.id: (regulator.code, regulation.code)
        for regulation, regulator in db.execute(select(Regulation, Regulator).join(Regulator, Regulation.regulator_id == Regulator.id)).all()
    }

    all_rows = db.execute(
        select(Action.id, Action.change_id, Action.status, Action.due_date, Action.assignee_name)
    ).all()

    def due_of(row) -> date | None:
        if row.due_date is not None:
            return row.due_date
        p = prio.get(row.change_id)
        return p.due_date if p else None

    # ── summary over every action, whatever the filters ──
    by_status = {s: 0 for s in L.ACTION_STATUSES}
    open_n = due_soon = overdue_open = pending_overdue = assigned_n = 0
    for r in all_rows:
        by_status[r.status] = by_status.get(r.status, 0) + 1
        if r.assignee_name:
            assigned_n += 1
        due = due_of(r)
        if r.status == "awaiting_confirmation":
            open_n += 1
            if due is not None:
                if due < today:
                    overdue_open += 1
                elif (due - today).days <= DUE_SOON_DAYS:
                    due_soon += 1
        if r.status == "pending" and due is not None and due < today:
            pending_overdue += 1
    summary = {
        "total": len(all_rows), "by_status": by_status, "open": open_n, "due_within_5_days": due_soon,
        "overdue": overdue_open, "pending_review": by_status.get("pending", 0),
        "pending_review_overdue": pending_overdue, "assigned": assigned_n,
    }

    # ── filter and sort (lightweight rows), then paginate ──
    rows = all_rows
    if wanted is not None:
        rows = [r for r in rows if r.status in wanted]
    if assigned is True:
        rows = [r for r in rows if r.assignee_name]
    elif assigned is False:
        rows = [r for r in rows if not r.assignee_name]
    if change_id is not None:
        rows = [r for r in rows if r.change_id == change_id]

    def overdue_flag(r) -> bool:
        due = due_of(r)
        return r.status in L.OPEN_STATUSES and due is not None and due < today

    rows = sorted(rows, key=lambda r: (not overdue_flag(r), due_of(r) or FAR_FUTURE, r.id))
    total = len(rows)
    page_ids = [r.id for r in rows[offset : offset + limit]]

    items: list[dict[str, Any]] = []
    if page_ids:
        actions = {a.id: a for a in db.scalars(select(Action).where(Action.id.in_(page_ids)))}
        owner_ids = {a.owner_node_id for a in actions.values() if a.owner_node_id}
        owners = {n.id: n.name for n in db.scalars(select(OrgNode).where(OrgNode.id.in_(owner_ids)))} if owner_ids else {}
        last_events = dict(
            db.execute(
                select(AuditLog.ref_id, func.max(AuditLog.ts))
                .where(AuditLog.ref_type == "action", AuditLog.ref_id.in_(page_ids))
                .group_by(AuditLog.ref_id)
            ).all()
        )
        for action_id in page_ids:
            a = actions[action_id]
            change = change_by_id.get(a.change_id)
            p = prio.get(a.change_id)
            payload = a.payload_json if isinstance(a.payload_json, dict) else {}
            due = a.due_date or (p.due_date if p else None)
            type_en, type_ar = L.action_type_label(a.type)
            status_en, status_ar = L.status_label(a.status)
            regulator_code, regulation_code = reg_map.get(change.regulation_id, (None, None)) if change else (None, None)
            last_event = last_events.get(a.id) or a.created_at
            items.append({
                "id": a.id, "action_type": a.type, "action_type_label_en": type_en, "action_type_label_ar": type_ar,
                "level": a.level, "status": a.status, "status_label_en": status_en, "status_label_ar": status_ar,
                "change_id": a.change_id,
                "change_title_en": change.summary_en if change else "", "change_title_ar": change.summary_ar if change else "",
                "clause_ref": (change.new_clause_id or change.old_clause_id) if change else payload.get("clause_id"),
                "regulator_code": regulator_code, "regulation_code": regulation_code,
                "priority_band": p.band if p else None,
                "priority_key": L.BAND_TO_MATRIX_KEY.get(p.band) if p else None,
                "priority_score": p.score if p else None,
                "due_date": due,
                "is_overdue": a.status in L.OPEN_STATUSES and due is not None and due < today,
                "days_left": (due - today).days if due is not None else None,
                "assignee_name": a.assignee_name, "assignee_contact": a.assignee_contact,
                "owner_node_name": clean(owners.get(a.owner_node_id)),
                "impact_node_name": clean(payload.get("impact_node_name")),
                "erp": _erp_view(payload.get("erp")),
                "effect": _effect_view(payload.get("effect"), include_effect_diff),
                "delegated_at": as_utc(a.delegated_at), "confirmed_at": as_utc(a.confirmed_at),
                "created_at": as_utc(a.created_at), "last_event_at": as_utc(last_event),
            })

    return {"items": items, "total": total, "limit": limit, "offset": offset, "summary": summary}
