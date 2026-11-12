"""
Demo pipeline routes: the one-click live demo.

  GET  /demo/status  where the demo is (baseline | scanning | review_ready)
  GET  /demo/run     the current or last scan, with per-stage live progress
  POST /demo/scan    start the live pipeline in the background (one at a time)
  POST /demo/reset   back to "company on ECC-1:2018 only" (destructive)

/demo/reset and /demo/scan are gated by demo mode (DEMO_MODE, default true in
dev): with it off they answer 403 and change nothing. See app/demo/.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import require_user
from ..config import settings
from ..db.models import AppUser
from ..db.session import get_db
from ..demo import baseline, runner
from ..demo.status import compute_status
from ..demo.tracker import TRACKER, DemoConflict

router = APIRouter(prefix="/demo", tags=["demo"])


def _require_demo_mode() -> None:
    if not settings.demo_mode:
        raise HTTPException(
            status_code=403,
            detail="Demo mode is off (DEMO_MODE=false): the demo reset and scan endpoints are disabled.",
        )


@router.get("/status")
def demo_status(db: Session = Depends(get_db)) -> dict[str, Any]:
    return compute_status(db)


@router.get("/run")
def demo_run() -> dict[str, Any]:
    return TRACKER.snapshot()


@router.post("/scan", status_code=202)
def demo_scan(user: AppUser = Depends(require_user)) -> dict[str, Any]:
    _require_demo_mode()
    try:
        return runner.start_scan(actor=user.actor())
    except DemoConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/reset")
def demo_reset(user: AppUser = Depends(require_user)) -> dict[str, Any]:
    _require_demo_mode()
    try:
        return baseline.reset_to_baseline(source="api", actor=user.actor())
    except DemoConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except baseline.DemoResetError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
