"""
GET /changes/{id}/export/{pdf,excel,oscal} — the M8 per-change exports
(takeoff prompt section 3/M8). Each builds directly from the same
database this process just queried; nothing here trusts client input
beyond the change id in the URL, matching the read pattern already
established in routes/changes.py.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Change, Regulation, Regulator
from ..db.session import get_db
from ..exports.excel import build_assessment_workbook, workbook_filename
from ..exports.oscal import build_oscal_export, oscal_filename
from ..exports.pdf import pdf_filename, render_change_pdf
from ..exports.summary_pdf import render_summary_pdf, summary_pdf_filename
from .changes import compute_priority_for_change

router = APIRouter(tags=["exports"])


def _get_change_or_404(db: Session, change_id: int) -> Change:
    change = db.get(Change, change_id)
    if change is None:
        raise HTTPException(status_code=404, detail=f"No change with id {change_id}.")
    return change


@router.get("/changes/{change_id}/export/pdf")
def export_change_pdf(change_id: int, db: Session = Depends(get_db)):
    change = _get_change_or_404(db, change_id)
    score, band = compute_priority_for_change(db, change)
    try:
        pdf_bytes = render_change_pdf(db, change, priority_score=score, priority_band=band)
    except RuntimeError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{pdf_filename(change)}"'},
    )


@router.get("/changes/{change_id}/export/excel")
def export_change_excel(change_id: int, db: Session = Depends(get_db)):
    change = _get_change_or_404(db, change_id)
    workbook_bytes = build_assessment_workbook(db, change)
    return Response(
        content=workbook_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{workbook_filename(change)}"'},
    )


@router.get("/changes/{change_id}/export/oscal")
def export_change_oscal(change_id: int, db: Session = Depends(get_db)):
    change = _get_change_or_404(db, change_id)
    payload = build_oscal_export(db, change)
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": f'attachment; filename="{oscal_filename(change)}"'},
    )


@router.get("/exports/summary")
def export_summary_pdf(
    db: Session = Depends(get_db),
    regulator: str | None = Query(None, description="Regulator code, e.g. 'nca' (matches Regulator.code)"),
    since: date | None = Query(None, description="Only include changes with created_at on or after this date"),
    band: str | None = Query(None, description="Filter to one priority band: critical|high|medium|low"),
):
    stmt = select(Change).where(Change.material.is_(True), Change.change_type.isnot(None))
    if regulator is not None:
        stmt = stmt.join(Regulation, Regulation.id == Change.regulation_id).join(
            Regulator, Regulator.id == Regulation.regulator_id
        ).where(Regulator.code == regulator)
    if since is not None:
        stmt = stmt.where(Change.created_at >= since)
    changes = list(db.scalars(stmt.order_by(Change.id)))

    scored = [(change, *compute_priority_for_change(db, change)) for change in changes]
    if band is not None:
        scored = [(change, score, b) for change, score, b in scored if b == band]
    scored.sort(key=lambda row: row[1], reverse=True)
    ranked_changes = [change for change, _score, _band in scored]

    filters = {"regulator": regulator, "since": since.isoformat() if since else None, "band": band}
    try:
        pdf_bytes = render_summary_pdf(db, ranked_changes, filters=filters)
    except RuntimeError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{summary_pdf_filename(filters)}"'},
    )
