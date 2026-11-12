"""
GET /settings/policy — the automation policy matrix for M7's Settings
screen. PUT /settings/policy (added once app/auth.py existed: see that
module and app/policy.py's "Editing" section for why this was correctly
deferred at first and what changed) lets an admin-role reviewer request
a different automation level per action type; every hard gate in
app/policy.py still applies regardless of what is requested here, exactly
as it does to a hand-edited YAML file.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import audit
from .. import policy as policy_mod
from ..auth import require_admin
from ..db.models import AppUser
from ..db.session import get_db
from .schemas import PolicyGateOut, PolicyOut

router = APIRouter(tags=["settings"])

# Mirrors the four gates in app/policy.py's explain_automation() (G1-G4),
# restated here in plain language for the UI. Kept next to the import of
# the gate constants themselves so the two cannot silently drift without
# a reviewer noticing the mismatch in a diff.
_GATE_DESCRIPTIONS: list[PolicyGateOut] = [
    PolicyGateOut(
        id="change_type_not_auto_executable",
        description_en=(
            "Only 'clarification' and 'editorial' changes may ever auto-execute an action; "
            "every other change type is capped at draft-then-approve."
        ),
    ),
    PolicyGateOut(
        id="tracked_decision_change_type",
        description_en="A 'new_obligation' change always requires a tracked human approve/dismiss decision.",
    ),
    PolicyGateOut(
        id="action_type_not_auto_executable",
        description_en=(
            "Only 'collect_evidence' and 'notify_owner' actions may ever auto-execute; "
            "every other action type always goes to a human."
        ),
    ),
    PolicyGateOut(
        id="confidence_below_threshold",
        description_en="Classification confidence below 0.7 always requires human review, whatever the policy file requests.",
    ),
]


def _policy_out(policy: policy_mod.AutomationPolicy) -> PolicyOut:
    return PolicyOut(
        default_level=policy.default_level,
        action_types=list(policy_mod.ACTION_TYPES),
        automation_levels=list(policy_mod.AUTOMATION_LEVELS),
        action_levels={action_type: policy.requested_level(action_type) for action_type in policy_mod.ACTION_TYPES},
        auto_executable_change_types=sorted(policy_mod.AUTO_EXECUTABLE_CHANGE_TYPES),
        tracked_decision_change_types=sorted(policy_mod.TRACKED_DECISION_CHANGE_TYPES),
        auto_executable_action_types=sorted(policy_mod.AUTO_EXECUTABLE_ACTION_TYPES),
        min_auto_execute_confidence=policy_mod.MIN_AUTO_EXECUTE_CONFIDENCE,
        gates=_GATE_DESCRIPTIONS,
    )


@router.get("/settings/policy", response_model=PolicyOut)
def get_policy():
    return _policy_out(policy_mod.load_policy())


class UpdatePolicyRequest(BaseModel):
    default_level: str
    action_levels: dict[str, str]


@router.put("/settings/policy", response_model=PolicyOut)
def update_policy(
    body: UpdatePolicyRequest, db: Session = Depends(get_db), user: AppUser = Depends(require_admin)
):
    """Admin-role only (app/auth.py). Every hard gate in app/policy.py still
    applies to the saved file exactly as before; this can only ever
    REQUEST a level, never force one past a gate (see that module's
    docstring, restated here deliberately rather than assumed obvious)."""
    before = policy_mod.load_policy()
    try:
        requested = policy_mod.parse_policy(
            {"default_level": body.default_level, "action_levels": body.action_levels},
            source="<PUT /settings/policy>",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    policy_mod.save_policy(requested)
    after = policy_mod.load_policy()
    audit.record(
        db,
        actor=user.actor(),
        event="policy_updated",
        ref_type="policy",
        payload={
            "previous": {"default_level": before.default_level, "action_levels": dict(before.action_levels)},
            "new": {"default_level": after.default_level, "action_levels": dict(after.action_levels)},
        },
    )
    return _policy_out(after)
