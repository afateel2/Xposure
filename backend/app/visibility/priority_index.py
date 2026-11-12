"""
Bulk priority band per change, using exactly the same arithmetic as
routes/changes.py (priority.compute_priority with the live impacted-node
count, days to the effective date and the regulator weight). Priority is not
stored on Change, so anything that needs a band for many changes at once
(overview, tasks, new-count) recomputes it here in a handful of queries rather
than one query per change.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import priority as priority_mod
from ..db.models import Change, Impact, Regulation, Regulator


@dataclass(frozen=True)
class Prio:
    score: int
    band: str  # critical | high | medium | low
    impacted: int
    due_date: date | None
    days_to_effective: int | None


def change_due_date(change: Change) -> date | None:
    """effective_date plus the stated grace period; None when the regulator
    gave no date (mirrors routes/changes.py and agent/graph.py)."""
    if change.effective_date is None:
        return None
    if change.grace_days:
        return change.effective_date + timedelta(days=change.grace_days)
    return change.effective_date


def load_priority_index(db: Session, changes: Iterable[Change]) -> dict[int, Prio]:
    """change id -> Prio, skipping unclassified changes (change_type is None
    has no priority, and inventing one would bury it)."""
    changes = [c for c in changes if c.change_type is not None]
    if not changes:
        return {}
    impact_counts = dict(db.execute(select(Impact.change_id, func.count()).group_by(Impact.change_id)).all())
    weights = dict(
        db.execute(select(Regulation.id, Regulator.weight).join(Regulator, Regulation.regulator_id == Regulator.id)).all()
    )
    today = date.today()
    out: dict[int, Prio] = {}
    for change in changes:
        days = (change.effective_date - today).days if change.effective_date else None
        impacted = int(impact_counts.get(change.id, 0))
        try:
            score, band = priority_mod.compute_priority(
                change, impacted, days, regulator_weight=float(weights.get(change.regulation_id, 1.0))
            )
        except ValueError:
            continue
        out[change.id] = Prio(score=score, band=band, impacted=impacted, due_date=change_due_date(change), days_to_effective=days)
    return out
