"""GET /agent/status — surfaces the agent loop's own audit trail (when it
last scanned for new sources, when it last ran to completion or failed)
for the Dashboard screen. Reads audit_log directly rather than adding a
new signal: check_sources_node and deliver_node/run_once already write
these events on every real run."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import eval_summary as eval_summary_mod
from ..db.models import AuditLog
from ..db.session import get_db
from .schemas import AgentStatusOut, DigestStatusOut, EvalSummaryOut

router = APIRouter(tags=["agent"])


@router.get("/agent/status", response_model=AgentStatusOut)
def get_agent_status(db: Session = Depends(get_db)):
    last_checked = db.scalar(
        select(AuditLog).where(AuditLog.event == "sources_checked").order_by(AuditLog.id.desc())
    )
    last_delivered = db.scalar(
        select(AuditLog).where(AuditLog.event == "run_delivered").order_by(AuditLog.id.desc())
    )
    last_failed = db.scalar(
        select(AuditLog).where(AuditLog.event == "run_failed").order_by(AuditLog.id.desc())
    )

    last_run, last_run_status = None, None
    if last_delivered and (not last_failed or last_delivered.id > last_failed.id):
        last_run, last_run_status = last_delivered, "delivered"
    elif last_failed:
        last_run, last_run_status = last_failed, "failed"

    last_baseline = db.scalar(
        select(AuditLog).where(AuditLog.event == "baseline_ingested").order_by(AuditLog.id.desc())
    )
    baseline_label = None
    if last_baseline:
        p = last_baseline.payload_json or {}
        baseline_label = f"{str(p.get('regulator', '?')).upper()} / {str(p.get('regulation', '?')).upper()} {p.get('version_label', '')}".strip()

    return AgentStatusOut(
        last_checked_at=last_checked.ts if last_checked else None,
        last_run_at=last_run.ts if last_run else None,
        last_run_status=last_run_status,
        last_run_summary=(last_run.payload_json if last_run else None),
        last_baseline_ingested_at=last_baseline.ts if last_baseline else None,
        last_baseline_ingested_label=baseline_label,
    )


@router.get("/agent/eval-summary", response_model=EvalSummaryOut | None)
def get_eval_summary():
    """Surfaces tests/eval_diff.py's own accuracy-on-labeled number for
    the Settings screen's trust-calibration display. Returns null,
    honestly, if no eval has ever been run for the currently configured
    model — never a fabricated 0% or a stale number from a different
    candidate model."""
    summary = eval_summary_mod.load_latest_eval_summary()
    return EvalSummaryOut(**summary) if summary else None


@router.get("/agent/digest-status", response_model=DigestStatusOut)
def get_digest_status(db: Session = Depends(get_db)):
    last = db.scalar(
        select(AuditLog)
        .where(AuditLog.event.in_(("digest_sent", "digest_skipped")))
        .order_by(AuditLog.id.desc())
    )
    if last is None:
        return DigestStatusOut(last_digest_at=None, last_digest_status=None, last_digest_summary=None)
    return DigestStatusOut(
        last_digest_at=last.ts,
        last_digest_status="sent" if last.event == "digest_sent" else "skipped",
        last_digest_summary=last.payload_json,
    )
