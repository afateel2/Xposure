"""
GET /changes (list) and GET /changes/{id} (detail — the "diff receipt" plus
impacted nodes and their actions).

Priority is never stored on Change (see agent/graph.py's apply_policy_node
comment: "priority has no column on `change` in the shared schema, so the
score travels with the action instead"). Actions only exist for changes
that produced at least one Impact, so a change with zero impacted nodes
has no Action row to read a score off of. Rather than depend on whether
the agent loop has run, these routes recompute priority.compute_priority()
directly — it is a pure, deterministic function (app/priority.py), so
recomputing it here gives the exact same number apply_policy_node already
persisted, for every change, not just the ones with actions.
"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import citation as citation_mod
from .. import priority as priority_mod
from ..db.models import Action, AuditLog, Change, Clause, Impact, OrgNode, Regulation, Regulator, RegulationVersion
from ..db.session import get_db
from .actions import TRANSITION_EVENTS
from .schemas import (
    ActionOut,
    ChangeDetailOut,
    ChangeSummaryOut,
    CitationCheckOut,
    CitationOut,
    ImpactOut,
    PriorityBreakdownOut,
    RegulationOut,
    RegulatorOut,
)


def _undo_state_by_action_id(db: Session, action_ids: list[int]) -> dict[int, bool]:
    """True per action id if its MOST RECENT transition-event row (see
    routes/actions.py's TRANSITION_EVENTS) is itself action_status_reverted
    — meaning the action was already undone once, so the frontend's next
    "Undo" click would actually be a redo (undo_action() is a self-inverting
    toggle: the same endpoint, called again, restores the prior state).
    Absence from the returned dict means no transition exists yet (nothing
    to undo). Batched over all of a change's actions in one query rather
    than one per action, ordered newest-first so the first row seen per
    action id in Python is its most recent."""
    if not action_ids:
        return {}
    rows = db.scalars(
        select(AuditLog)
        .where(AuditLog.ref_type == "action", AuditLog.ref_id.in_(action_ids), AuditLog.event.in_(TRANSITION_EVENTS))
        .order_by(AuditLog.id.desc())
    )
    latest_event_by_action: dict[int, str] = {}
    for row in rows:
        latest_event_by_action.setdefault(row.ref_id, row.event)
    return {action_id: event == "action_status_reverted" for action_id, event in latest_event_by_action.items()}

router = APIRouter(tags=["changes"])


def _due_date(change: Change) -> date | None:
    """Mirrors agent/graph.py's private _due_date() exactly (effective_date
    plus grace_days if the regulator stated one, else None — never
    guessed). Not imported from there: that helper is private to the agent
    module by its leading underscore, and this is three lines of pure
    arithmetic, not worth reaching into another milestone's internals for."""
    if change.effective_date is None:
        return None
    if change.grace_days:
        return change.effective_date + timedelta(days=change.grace_days)
    return change.effective_date


def _regulator_weight(db: Session, regulation_id: int, cache: dict[int, float]) -> float:
    if regulation_id in cache:
        return cache[regulation_id]
    weight = db.scalar(
        select(Regulator.weight)
        .join(Regulation, Regulation.regulator_id == Regulator.id)
        .where(Regulation.id == regulation_id)
    )
    if weight is None:
        raise HTTPException(
            status_code=500,
            detail=f"Could not resolve a regulator weight for regulation_id={regulation_id}.",
        )
    cache[regulation_id] = float(weight)
    return cache[regulation_id]


def compute_priority_for_change(db: Session, change: Change) -> tuple[int, str]:
    """Public single-change wrapper around the same primitives
    _build_summary uses (impacted-node count, days-to-effective, resolved
    regulator weight) — exposed so app/exports/pdf.py (M8) can put the
    identical, deterministic priority on a PDF that a UI screen would show
    for the same change, without either module re-deriving the other's
    plumbing."""
    if change.change_type is None:
        raise HTTPException(
            status_code=500,
            detail=f"Change {change.id} has never been classified (change_type is null).",
        )
    impacted_node_count = db.scalar(
        select(func.count()).select_from(Impact).where(Impact.change_id == change.id)
    )
    days_to_effective = (change.effective_date - date.today()).days if change.effective_date else None
    weight = _regulator_weight(db, change.regulation_id, {})
    return priority_mod.compute_priority(change, impacted_node_count, days_to_effective, regulator_weight=weight)


def _regulator_regulation_map(db: Session) -> dict[int, tuple[Regulator, Regulation]]:
    rows = db.execute(
        select(Regulation, Regulator).join(Regulator, Regulation.regulator_id == Regulator.id)
    ).all()
    return {regulation.id: (regulator, regulation) for regulation, regulator in rows}


def _is_overdue(due_date: date | None, action_status_counts: dict[str, int]) -> bool:
    """Overdue means the deadline has passed AND the change is still
    outstanding: either no action has been recorded for it yet, or at
    least one is still pending/awaiting_confirmation. A change whose every
    action already resolved to approved/dismissed/done is not overdue
    just because the clock ran out after the fact."""
    if due_date is None or due_date >= date.today():
        return False
    if not action_status_counts:
        return True
    return bool(action_status_counts.get("pending") or action_status_counts.get("awaiting_confirmation"))


def _build_summary(
    db: Session,
    change: Change,
    regulator: Regulator,
    regulation: Regulation,
    impacted_node_count: int,
    action_status_counts: dict[str, int],
    weight_cache: dict[int, float],
    assigned_to: list[str] | None = None,
) -> ChangeSummaryOut:
    if change.change_type is None:
        raise HTTPException(
            status_code=500,
            detail=f"Change {change.id} has never been classified (change_type is null): "
            "run `python -m app.diff` before serving it through this API.",
        )
    due_date = _due_date(change)
    days_to_effective = (
        (change.effective_date - date.today()).days if change.effective_date else None
    )
    breakdown = priority_mod.explain_priority(
        change,
        impacted_node_count,
        days_to_effective,
        regulator_weight=_regulator_weight(db, change.regulation_id, weight_cache),
    )
    return ChangeSummaryOut(
        id=change.id,
        regulator=RegulatorOut(code=regulator.code, name_en=regulator.name_en, name_ar=regulator.name_ar),
        regulation=RegulationOut(code=regulation.code, title_en=regulation.title_en, title_ar=regulation.title_ar),
        old_clause_id=change.old_clause_id,
        new_clause_id=change.new_clause_id,
        clause_ref=change.new_clause_id or change.old_clause_id,
        match_kind=change.match_kind,
        change_type=change.change_type,
        material=change.material,
        confidence=change.confidence,
        summary_en=change.summary_en,
        summary_ar=change.summary_ar,
        effective_date=change.effective_date,
        grace_days=change.grace_days,
        due_date=due_date,
        priority_score=breakdown["score"],
        priority_band=breakdown["band"],
        priority_breakdown=PriorityBreakdownOut(
            severity_weight=breakdown["severity_weight"],
            impact_factor=breakdown["impact_factor"],
            deadline_factor=breakdown["deadline_factor"],
            regulator_weight=breakdown["regulator_weight"],
            raw=breakdown["raw"],
            reference_raw=breakdown["reference_raw"],
            ungated_score=breakdown["ungated_score"],
            gate=breakdown["gate"],
        ),
        days_to_effective=days_to_effective,
        is_overdue=_is_overdue(due_date, action_status_counts),
        impacted_node_count=impacted_node_count,
        action_status_counts=action_status_counts,
        assigned_to=assigned_to or [],
        created_at=change.created_at,
    )


@router.get("/changes", response_model=list[ChangeSummaryOut])
def list_changes(
    db: Session = Depends(get_db),
    material_only: bool = Query(True, description="Only return material=true changes (the default UI view)"),
    band: str | None = Query(None, description="Filter to one priority band: critical|high|medium|low"),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    stmt = select(Change)
    if material_only:
        stmt = stmt.where(Change.material.is_(True))
    changes = list(db.scalars(stmt.order_by(Change.id)))

    reg_map = _regulator_regulation_map(db)
    impact_counts = dict(
        db.execute(select(Impact.change_id, func.count()).group_by(Impact.change_id)).all()
    )
    status_rows = db.execute(
        select(Action.change_id, Action.status, func.count()).group_by(Action.change_id, Action.status)
    ).all()
    status_counts: dict[int, dict[str, int]] = {}
    for change_id, status, count in status_rows:
        status_counts.setdefault(change_id, {})[status] = count

    assignee_rows = db.execute(
        select(Action.change_id, Action.assignee_name).where(Action.assignee_name.isnot(None)).distinct()
    ).all()
    assignees_by_change: dict[int, list[str]] = {}
    for change_id, assignee_name in assignee_rows:
        assignees_by_change.setdefault(change_id, []).append(assignee_name)

    weight_cache: dict[int, float] = {}
    out: list[ChangeSummaryOut] = []
    for change in changes:
        regulator, regulation = reg_map[change.regulation_id]
        summary = _build_summary(
            db,
            change,
            regulator,
            regulation,
            impact_counts.get(change.id, 0),
            status_counts.get(change.id, {}),
            weight_cache,
            assigned_to=assignees_by_change.get(change.id),
        )
        if band is not None and summary.priority_band != band:
            continue
        out.append(summary)

    out.sort(key=lambda c: (-c.priority_score, c.id))
    return out[offset : offset + limit]


@router.get("/changes/{change_id}", response_model=ChangeDetailOut)
def get_change(change_id: int, db: Session = Depends(get_db)):
    change = db.get(Change, change_id)
    if change is None:
        raise HTTPException(status_code=404, detail=f"No change with id {change_id}.")

    regulator = db.scalar(
        select(Regulator).join(Regulation, Regulation.regulator_id == Regulator.id).where(
            Regulation.id == change.regulation_id
        )
    )
    regulation = db.get(Regulation, change.regulation_id)
    if regulator is None or regulation is None:
        raise HTTPException(status_code=500, detail=f"Change {change_id} has no resolvable regulation/regulator.")

    impact_count = db.scalar(select(func.count()).select_from(Impact).where(Impact.change_id == change_id))
    status_counts_rows = db.execute(
        select(Action.status, func.count()).where(Action.change_id == change_id).group_by(Action.status)
    ).all()
    status_counts = dict(status_counts_rows)
    assigned_to = [
        name for (name,) in db.execute(
            select(Action.assignee_name)
            .where(Action.change_id == change_id, Action.assignee_name.isnot(None))
            .distinct()
        ).all()
    ]

    summary = _build_summary(
        db, change, regulator, regulation, impact_count, status_counts, {}, assigned_to=assigned_to
    )

    from_version = db.get(RegulationVersion, change.from_version_id)
    to_version = db.get(RegulationVersion, change.to_version_id)

    old_clause = (
        db.scalar(select(Clause).where(Clause.version_id == change.from_version_id, Clause.clause_id == change.old_clause_id))
        if change.old_clause_id
        else None
    )
    new_clause = (
        db.scalar(select(Clause).where(Clause.version_id == change.to_version_id, Clause.clause_id == change.new_clause_id))
        if change.new_clause_id
        else None
    )

    impacts = list(db.scalars(select(Impact).where(Impact.change_id == change_id).order_by(Impact.id)))
    node_ids = {impact.node_id for impact in impacts}
    nodes_by_id = {n.id: n for n in db.scalars(select(OrgNode).where(OrgNode.id.in_(node_ids)))} if node_ids else {}

    actions = list(db.scalars(select(Action).where(Action.change_id == change_id).order_by(Action.id)))
    actions_by_impact_id: dict[int, list[Action]] = {}
    for action in actions:
        impact_id = (action.payload_json or {}).get("impact_id")
        actions_by_impact_id.setdefault(impact_id, []).append(action)
    is_redo_by_action_id = _undo_state_by_action_id(db, [a.id for a in actions])

    impact_out: list[ImpactOut] = []
    for impact in impacts:
        node = nodes_by_id.get(impact.node_id)
        path = impact.path_json or {}
        impact_actions = [
            ActionOut(
                id=a.id,
                type=a.type,
                level=a.level,
                status=a.status,
                due_date=_due_date(change),
                owner_node_name=(nodes_by_id[a.owner_node_id].name if a.owner_node_id in nodes_by_id else None),
                created_at=a.created_at,
                assignee_name=a.assignee_name,
                assignee_contact=a.assignee_contact,
                delegated_at=a.delegated_at,
                confirmed_at=a.confirmed_at,
                can_undo=a.id in is_redo_by_action_id,
                is_redo=is_redo_by_action_id.get(a.id, False),
                effect=(a.payload_json or {}).get("effect"),
                erp=(a.payload_json or {}).get("erp"),
                automation_requested=(a.payload_json or {}).get("automation_requested"),
                automation_gates=(a.payload_json or {}).get("automation_gates"),
                # Only meaningful while dismissed: an undone dismissal keeps the
                # old key in the payload but is no longer dismissed.
                dismiss_reason=(a.payload_json or {}).get("dismiss_reason") if a.status == "dismissed" else None,
            )
            for a in actions_by_impact_id.get(impact.id, [])
        ]
        impact_out.append(
            ImpactOut(
                id=impact.id,
                node_id=impact.node_id,
                node_type=node.type if node else "unknown",
                node_name=node.name if node else f"node #{impact.node_id}",
                scope_match=path.get("scope_match", ""),
                depth=path.get("depth", 0),
                path_summary=path.get("summary", node.name if node else ""),
                note_en=impact.note_en,
                note_ar=impact.note_ar,
                recommended_actions=impact.recommended_actions_json or [],
                actions=impact_actions,
            )
        )

    return ChangeDetailOut(
        **summary.model_dump(),
        match_score=change.match_score,
        old_text_en=old_clause.text_en if old_clause else None,
        old_text_ar=old_clause.text_ar if old_clause else None,
        new_text_en=new_clause.text_en if new_clause else None,
        new_text_ar=new_clause.text_ar if new_clause else None,
        old_page=old_clause.page_en if old_clause else None,
        new_page=new_clause.page_en if new_clause else None,
        old_version_label=from_version.version_label if from_version else None,
        new_version_label=to_version.version_label if to_version else None,
        from_file_sha256=from_version.file_sha256 if from_version else "",
        to_file_sha256=to_version.file_sha256 if to_version else "",
        diff_ops=(change.diff_spans_json or {}).get("ops", []),
        impacts=impact_out,
        citation=CitationOut(
            old=_citation_for(regulator, regulation, from_version, old_clause),
            new=_citation_for(regulator, regulation, to_version, new_clause),
        ),
    )


def _citation_for(
    regulator: Regulator, regulation: Regulation, version: RegulationVersion | None, clause: Clause | None
) -> CitationCheckOut | None:
    """Is this clause's text really in the stored source file (app/citation.py)?
    None when there is no clause on this side (a pure new or withdrawn change).
    Never raises: a problem reading the file becomes an 'unavailable' result,
    because a missing check must not break the page that shows the change."""
    if clause is None or version is None:
        return None
    try:
        result = citation_mod.check_clause_text(
            citation_mod.source_pdf_path(regulator.code, regulation.code, version.version_label),
            version.file_sha256,
            clause.text_en,
            clause.page_en,
        )
    except Exception as exc:
        result = citation_mod.CitationCheck(status="unavailable", cited_page=clause.page_en, reason=type(exc).__name__)
    return CitationCheckOut(
        status=result.status,
        page=result.page,
        cited_page=result.cited_page,
        file_hash_ok=result.file_hash_ok,
        reason=result.reason,
    )
