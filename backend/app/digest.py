"""
Periodic digest of newly-appeared critical/high material changes and
newly-overdue pending actions, delivered via app/notify.py and mirrored to
app/webhooks.py — the "what's new since I last looked" complement to the
on-demand /changes list. Runnable as `python -m app.digest`: this codebase
has no in-app scheduler anywhere, so an external one (cron / Windows Task
Scheduler) is expected to invoke this module directly; this file is the
thing that gets scheduled, not the scheduler itself.

The watermark is the audit trail itself: the most recent `digest_sent`
AuditLog row's `ts`, the identical shape routes/agent.py already uses for
"when did X last happen" (`sources_checked` / `run_delivered` /
`run_failed`). No separate watermark table — a `digest_sent` row only
exists when a real digest actually went out, so the row and the watermark
it establishes are written together and can never drift apart.
"""

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import audit, notify, webhooks
from . import priority as priority_mod
from .config import settings
from .db.models import Action, AuditLog, Change, Impact, Regulation, Regulator
from .db.session import get_engine

_REPORTED_BANDS = frozenset({"critical", "high"})


def _due_date(change: Change) -> date | None:
    """Mirrors routes/changes.py's _due_date() (itself mirroring
    agent/graph.py's private helper) exactly: effective_date plus
    grace_days if the regulator stated one, else effective_date, else
    None — never guessed. Restated rather than imported: that helper is
    private to its own module by its leading underscore, and this is
    three lines of pure arithmetic, not worth reaching into another
    module's internals for."""
    if change.effective_date is None:
        return None
    if change.grace_days:
        return change.effective_date + timedelta(days=change.grace_days)
    return change.effective_date


def _last_digest_ts(db: Session) -> datetime | None:
    last = db.scalar(
        select(AuditLog).where(AuditLog.event == "digest_sent").order_by(AuditLog.id.desc())
    )
    return last.ts if last else None


def _new_critical_or_high_changes(db: Session, watermark: datetime | None) -> list[dict[str, Any]]:
    stmt = select(Change).where(Change.material.is_(True))
    stmt = (
        stmt.where(Change.created_at > watermark)
        if watermark is not None
        else stmt.where(Change.created_at.isnot(None))
    )
    changes = list(db.scalars(stmt.order_by(Change.id)))
    if not changes:
        return []

    impact_counts = dict(
        db.execute(select(Impact.change_id, func.count()).group_by(Impact.change_id)).all()
    )
    weight_cache: dict[int, float] = {}

    out: list[dict[str, Any]] = []
    for change in changes:
        if change.change_type is None:
            # Unclassified — priority.compute_priority has no band for it
            # yet (diff.py hasn't classified it), so it cannot be judged
            # critical/high or not. It will be picked up once classified.
            continue
        if change.regulation_id not in weight_cache:
            weight = db.scalar(
                select(Regulator.weight)
                .join(Regulation, Regulation.regulator_id == Regulator.id)
                .where(Regulation.id == change.regulation_id)
            )
            weight_cache[change.regulation_id] = (
                float(weight) if weight is not None else priority_mod.DEFAULT_REGULATOR_WEIGHT
            )
        days_to_effective = (
            (change.effective_date - date.today()).days if change.effective_date else None
        )
        _score, band = priority_mod.compute_priority(
            change,
            impact_counts.get(change.id, 0),
            days_to_effective,
            regulator_weight=weight_cache[change.regulation_id],
        )
        if band not in _REPORTED_BANDS:
            continue
        out.append(
            {
                "id": change.id,
                "clause_ref": change.new_clause_id or change.old_clause_id,
                "change_type": change.change_type,
                "band": band,
                "summary_en": change.summary_en,
            }
        )
    return out


def _newly_overdue_actions(db: Session, watermark: datetime | None) -> list[dict[str, Any]]:
    """An action is "newly overdue for this digest" when its change's
    due_date has crossed into overdue territory since the last digest:
    due_date < today() (it IS overdue now) AND due_date >= the last
    digest's watermark date (it was NOT yet overdue — or didn't exist —
    as of the last digest, so this is genuinely new, not a repeat of
    something already reported) — AND the action itself is still
    status == "pending" (approved/dismissed/awaiting_confirmation/done
    actions are no longer "the compliance officer's problem"). On the very
    first digest (watermark is None) every currently-overdue pending
    action counts, since nothing has ever been reported yet.
    """
    today = date.today()
    pending = list(db.scalars(select(Action).where(Action.status == "pending")))
    if not pending:
        return []

    change_ids = {a.change_id for a in pending}
    changes_by_id = {c.id: c for c in db.scalars(select(Change).where(Change.id.in_(change_ids)))}
    watermark_date = watermark.date() if watermark is not None else None

    out: list[dict[str, Any]] = []
    for action in pending:
        change = changes_by_id.get(action.change_id)
        if change is None:
            continue
        due_date = _due_date(change)
        if due_date is None or due_date >= today:
            continue
        if watermark_date is not None and due_date < watermark_date:
            continue
        out.append(
            {
                "id": action.id,
                "type": action.type,
                "due_date": due_date.isoformat(),
                "change_id": change.id,
            }
        )
    return out


def _summary_text(
    watermark: datetime | None, changes: list[dict[str, Any]], actions: list[dict[str, Any]]
) -> str:
    lines = [
        "Xposure digest" + (f", since {watermark.isoformat()}" if watermark else ", first run"),
        "",
        f"New critical/high material changes: {len(changes)}",
    ]
    for c in changes:
        lines.append(
            f"  - Change #{c['id']} [{c['band']}] {c['clause_ref'] or '(no clause ref)'}: "
            f"{c['change_type']}: {c['summary_en']}"
        )
    lines.append("")
    lines.append(f"Newly overdue actions: {len(actions)}")
    for a in actions:
        lines.append(f"  - Action #{a['id']} ({a['type']}) on change #{a['change_id']}, due {a['due_date']}")
    return "\n".join(lines)


def build_digest(db: Session) -> dict[str, Any] | None:
    """Returns None when there is genuinely nothing new to report since
    the last digest (no fresh critical/high material change, no action
    that crossed into overdue) — an empty digest must not be sent, and
    this is how the caller knows that, honestly, rather than mailing an
    empty body.

    Otherwise returns {"since", "new_critical_or_high_changes",
    "newly_overdue_actions", "summary_text"} — see this module's docstring
    for the watermark, and _newly_overdue_actions for the exact "newly
    overdue" rule."""
    watermark = _last_digest_ts(db)
    changes = _new_critical_or_high_changes(db, watermark)
    actions = _newly_overdue_actions(db, watermark)
    if not changes and not actions:
        return None
    return {
        "since": watermark.isoformat() if watermark else None,
        "new_critical_or_high_changes": changes,
        "newly_overdue_actions": actions,
        "summary_text": _summary_text(watermark, changes, actions),
    }


def run_digest_cli() -> None:
    """`python -m app.digest` entry point. Opens its own session (no
    FastAPI request to hang a Depends(get_db) off), builds the digest, and
    — regardless of whether delivery actually succeeded — writes the audit
    row that becomes the next run's watermark: same "record what happened,
    not what we wish happened" discipline as the rest of this app."""
    with Session(get_engine()) as db:
        digest = build_digest(db)
        if digest is None:
            print("[digest] nothing to report")
            audit.record(
                db,
                actor="agent:digest",
                event="digest_skipped",
                payload={"reason": "nothing new since last digest"},
            )
            return

        notify_result = notify.send_notification(
            channel=None,
            target=settings.digest_recipient,
            subject="Xposure digest",
            message=digest["summary_text"],
            payload=digest,
        )
        webhook_result = None
        if "digest.sent" in webhooks.WEBHOOK_EVENTS:
            webhook_result = webhooks.send_webhook("digest.sent", digest)

        payload = dict(digest)
        payload["notify_result"] = notify_result
        payload["webhook_result"] = webhook_result
        audit.record(db, actor="agent:digest", event="digest_sent", payload=payload)
        print(
            f"[digest] sent: {len(digest['new_critical_or_high_changes'])} changes, "
            f"{len(digest['newly_overdue_actions'])} overdue actions"
        )


if __name__ == "__main__":
    run_digest_cli()
