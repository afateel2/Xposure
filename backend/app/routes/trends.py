"""
GET /trends — regulatory-change volume over time, broken down by regulator,
regulation, change_type, and priority band, for a frontend trend chart.

Grouping is done in Python over a plain SELECT, not via SQL
`date_trunc('month', ...)`. Two reasons: (1) this app's tests run against
in-memory SQLite (see tests/unit/test_routes.py), which has no
`date_trunc`, so a Postgres-only grouping expression would need a second
code path just for tests; (2) the whole `change` table is a few hundred
rows in this project, so pulling it into Python and grouping with a dict
costs nothing worth avoiding the dialect split for. If change volume ever
grew into the millions this would move back into SQL, but that is not this
app's shape.

Priority band here is computed with impacted_node_count=0 rather than a
real join against Impact grouped by change_id. This is a deliberate
simplification specific to this trend view (explicitly sanctioned — see
the task this file was built from): a trend chart answers "how much/how
severe over time", not "what is this one change's authoritative score",
and impact_factor's contribution is a sublinear multiplier (1.0-2.0x,
priority.py's IMPACT_GAIN/IMPACT_FACTOR_CEILING) that shifts a band at the
margins but never re-orders change_type severity. routes/changes.py's
per-change score (which *does* join Impact) remains the authoritative
number; this endpoint's bands are for chart shading, not for driving any
action.
"""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import priority as priority_mod
from ..db.models import Change, Regulation, Regulator
from ..db.session import get_db

router = APIRouter(tags=["trends"])


@router.get("/trends")
def get_trends(
    db: Session = Depends(get_db),
    group_by: Literal["month"] = Query("month", description="Only 'month' is supported for now."),
    regulator: str | None = Query(None, description="Filter to one regulator code"),
    regulation: str | None = Query(None, description="Filter to one regulation code"),
    material_only: bool = Query(True, description="Only include material=true changes (matches /changes' default)"),
):
    stmt = (
        select(Change, Regulator, Regulation)
        .join(Regulation, Change.regulation_id == Regulation.id)
        .join(Regulator, Regulation.regulator_id == Regulator.id)
    )
    if material_only:
        stmt = stmt.where(Change.material.is_(True))
    if regulator is not None:
        stmt = stmt.where(Regulator.code == regulator)
    if regulation is not None:
        stmt = stmt.where(Regulation.code == regulation)

    counts: dict[tuple[str, str, str, str, str], int] = {}
    for change, reg, regn in db.execute(stmt).all():
        # Unclassified changes (change_type is None) have no priority band
        # and no meaningful change_type to bucket by yet — same gate
        # routes/changes.py applies before computing priority, just skipped
        # here instead of raised, since a trend view should not 500 over
        # one unclassified row sitting in an otherwise-fine window.
        if change.change_type is None:
            continue
        days_to_effective = (change.effective_date - date.today()).days if change.effective_date else None
        _, band = priority_mod.compute_priority(change, 0, days_to_effective, regulator_weight=reg.weight)
        period = change.created_at.strftime("%Y-%m")
        key = (period, reg.code, regn.code, change.change_type, band)
        counts[key] = counts.get(key, 0) + 1

    return [
        {
            "period": period,
            "regulator_code": regulator_code,
            "regulation_code": regulation_code,
            "change_type": change_type,
            "band": band,
            "count": count,
        }
        for (period, regulator_code, regulation_code, change_type, band), count in sorted(counts.items())
    ]
