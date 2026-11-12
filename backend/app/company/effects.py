"""
The seam between the action routes and the executor: what happens to a
company file when a human approves, undoes or redoes an action, plus the
audit rows that record it. routes/actions.py calls these three functions and
nothing else from this package.

Approval never depends on the file edit: by the time the executor runs, the
decision is already committed. If the edit fails or is not applicable, the
approval stands, the response says so, and only a failure (not a plain "no
file mapped") leaves an `action_effect_failed` audit row.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .. import audit
from ..db.models import Action
from . import executor

ACTOR = "agent:executor"


def apply_after_approve(db: Session, action: Action) -> dict[str, Any]:
    """Run the executor for a single approval. Returns {"effect": dict | None, "effect_note": str | None}."""
    try:
        result = executor.execute_action(db, action)
    except Exception as exc:  # the decision is already recorded; never fail the approval over the file edit
        db.rollback()
        audit.record(
            db, actor=ACTOR, event="action_effect_failed", ref_type="action", ref_id=action.id,
            payload={"reason_code": "unexpected_error", "reason": f"{type(exc).__name__}: {exc}"},
        )
        return {"effect": None, "effect_note": f"No file effect: unexpected error ({type(exc).__name__})."}

    if result.applied and result.effect is not None:
        effect = result.effect
        audit.record(
            db, actor=ACTOR, event="action_effect_applied", ref_type="action", ref_id=action.id,
            payload={
                "change_id": action.change_id,
                "path": effect["path"],
                "version_before": effect["version_before"],
                "version_after": effect["version_after"],
                "added": effect["added"],
                "removed": effect["removed"],
                "cached": effect["cached"],
            },
        )
        return {"effect": effect, "effect_note": None}

    if result.reason_code in ("model_failed", "file_missing"):
        audit.record(
            db, actor=ACTOR, event="action_effect_failed", ref_type="action", ref_id=action.id,
            payload={"reason_code": result.reason_code, "reason": result.reason},
        )
    return {"effect": None, "effect_note": result.reason}


def revert_before_undo(
    db: Session, action: Action, target_status: str, *, actor: str = "user:web"
) -> tuple[dict[str, Any] | None, list[str]]:
    """If the undo leaves the approved state and the approval had a live file effect, restore the file.

    Returns (reverted effect or None, notes for side_effects_not_reversed).
    A revert that cannot be done cleanly (a newer version of the file exists)
    is reported as a note instead of silently overwriting that newer edit.
    Call this before the status transition. The audit row is written without
    committing; the caller's status transition commits it together."""
    if action.status != "approved" or target_status == "approved":
        return None, []
    reverted, note = executor.revert_action_effect(db, action)
    if reverted is not None:
        audit.record(
            db, actor=actor, event="action_effect_reverted", ref_type="action", ref_id=action.id,
            payload={
                "path": reverted["path"],
                "version_restored": reverted["version_restored"],
                "version_reverted": reverted["version_after"],
                "history_reverted": reverted["history_reverted"],
            },
            commit=False,
        )
    return reverted, ([note] if note else [])


def reapply_after_undo(db: Session, action: Action, old_status: str) -> dict[str, Any] | None:
    """Redo: an undo that returns an action to approved re-applies the file edit that an earlier undo reverted.

    Only when that approval actually had an effect (a bulk approval is
    decision-only and has nothing to reapply). The model answer is cached, so
    this is instant and identical when the file is unchanged since."""
    payload = action.payload_json or {}
    if old_status == "approved" or action.status != "approved":
        return None
    if "effect_reverted" not in payload or "effect" in payload:
        return None
    return apply_after_approve(db, action)["effect"]
