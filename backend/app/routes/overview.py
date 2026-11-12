"""
Visibility API, part 1: GET /overview and GET /changes/new-count. This module
also mounts the rest of the visibility routes (routes/activity.py: /activity,
/audit, /audit/events, /audit/actors, /agent/state, /changes/{id}/timeline;
routes/tasks.py: /tasks), so main.py registers ONE router for the whole layer.

Registration order matters: main.py must include this router BEFORE
routes/changes.py, because /changes/new-count would otherwise be captured by
/changes/{change_id} and fail integer validation.

Everything here is read-only against the database.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Change
from ..db.session import get_db
from ..visibility import labels as L
from ..visibility.overview import build_overview
from ..visibility.priority_index import load_priority_index
from ..visibility.schemas import NewCountOut, OverviewOut
from ..visibility.timeutil import as_utc, parse_iso, to_naive_utc
from . import activity, tasks

router = APIRouter(tags=["visibility"])


@router.get("/overview", response_model=OverviewOut)
def get_overview(
    since_reset: bool = Query(True, description="Limit scan and change timestamps to events after the last demo_reset (when one exists)."),
    db: Session = Depends(get_db),
):
    """One document for the dashboard: monitoring status, review queue, tasks,
    priority matrix, remediation progress and per-source status (planned
    regulators are listed but marked `planned`, never monitored)."""
    return build_overview(db, since_reset=since_reset)


@router.get("/changes/new-count", response_model=NewCountOut)
def get_new_change_count(
    since: str = Query(..., description="ISO-8601 timestamp (for example the last-seen time the browser keeps in localStorage)."),
    material_only: bool = Query(True, description="Count only material changes (matches /changes' default)."),
    db: Session = Depends(get_db),
):
    """How many changes were created after `since`, by priority band, for a
    'new since your last visit' badge."""
    try:
        since_dt = parse_iso(since)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"`since` must be an ISO-8601 timestamp, got {since!r}.") from None
    stmt = select(Change).where(Change.created_at > to_naive_utc(since_dt))
    if material_only:
        stmt = stmt.where(Change.material.is_(True))
    changes = list(db.scalars(stmt))
    prio = load_priority_index(db, changes)
    by_band = {b: 0 for b in ("critical", "high", "medium", "low")}
    for c in changes:
        if c.id in prio:
            by_band[prio[c.id].band] += 1
    by_matrix = {"critical": 0, "quick": 0, "strategic": 0, "followup": 0}
    for band, n in by_band.items():
        by_matrix[L.BAND_TO_MATRIX_KEY[band]] += n
    return NewCountOut(
        since=as_utc(since_dt), total=len(changes), by_band=by_band, by_matrix=by_matrix,
        latest_created_at=as_utc(max((c.created_at for c in changes), default=None)),
    )


router.include_router(activity.router)
router.include_router(tasks.router)
