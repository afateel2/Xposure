"""Turn an Xposure action into the text of an Odoo task.

The task must be self-contained for the person who receives it in Odoo:
what changed, which clause, what to do, how urgent, by when, and a link
back to Xposure. Plain HTML (Odoo's description field is Html), escaped,
and free of long dashes.
"""

from html import escape
from typing import Any

from sqlalchemy.orm import Session

from ..db.models import Action, Change, Regulation, Regulator
from .settings import get_erp_settings

ACTION_LABELS_EN = {
    "update_policy": "Update policy",
    "update_procedure": "Update procedure",
    "technical_change": "Technical change",
    "collect_evidence": "Collect evidence",
    "reassess_control": "Reassess control",
    "notify_owner": "Notify owner",
    "request_license_review": "Request license review",
}

_EM = chr(0x2014)
_EN = chr(0x2013)


def clean(text: str | None) -> str:
    """No long dashes in anything we write into Odoo."""
    return (text or "").replace(f" {_EM} ", ", ").replace(_EM, ",").replace(f" {_EN} ", ", ").replace(_EN, "-")


def _short(text: str, limit: int) -> str:
    text = " ".join(clean(text).split())
    if len(text) <= limit:
        return text
    cut = text[: limit - 3].rsplit(" ", 1)[0]
    return (cut or text[: limit - 3]) + "..."


def _first_sentence(text: str) -> str:
    text = " ".join(clean(text).split())
    for sep in (". ", "; "):
        if sep in text:
            return text.split(sep, 1)[0]
    return text.rstrip(".")


def xposure_link(change_id: int) -> str:
    return f"{get_erp_settings().xposure_public_url.rstrip('/')}/changes/{change_id}"


def action_label(action_type: str) -> str:
    return ACTION_LABELS_EN.get(action_type, action_type.replace("_", " ").capitalize())


def build_task_text(
    db: Session, action: Action, employee: dict[str, Any], note: str | None
) -> dict[str, Any]:
    """Returns {name, description_html, due_date, important, change_title,
    clause_ref, priority, link} for one action."""
    change = db.get(Change, action.change_id)
    regulation = db.get(Regulation, change.regulation_id) if change else None
    regulator = db.get(Regulator, regulation.regulator_id) if regulation else None
    payload = action.payload_json or {}

    clause_ref = (
        payload.get("clause_id")
        or (change.new_clause_id or change.old_clause_id if change else None)
        or "N/A"
    )
    reg_code = (regulation.code.upper() if regulation and regulation.code else "").strip()
    summary_en = clean(change.summary_en) if change else ""
    summary_ar = (change.summary_ar or "").strip() if change else ""
    change_type = (change.change_type or "").replace("_", " ") if change else ""
    change_title = _short(_first_sentence(summary_en), 90) or f"Change {action.change_id}"
    label = action_label(action.type)
    band = payload.get("priority_band") or "N/A"
    score = payload.get("priority_score")
    priority = f"{band} (score {score})" if score is not None else str(band)
    due = action.due_date.isoformat() if action.due_date else None
    link = xposure_link(action.change_id)
    target = payload.get("impact_node_name")

    ref = f"{reg_code} {clause_ref}".strip()
    name = _short(f"{label}: {change_title} ({ref})", 180)

    rows: list[tuple[str, str]] = [
        ("Change", change_title),
        ("Regulation", (regulation.title_en if regulation else "") or reg_code or "N/A"),
        ("Regulator", (regulator.name_en if regulator else "") or "N/A"),
        ("Clause reference", str(clause_ref)),
        ("Change type", change_type or "N/A"),
        ("Suggested action", label + (f" (impacted item: {target})" if target else "")),
        ("Priority", priority),
        ("Due date", due or "not set"),
        ("Assigned employee", employee.get("name") or "N/A"),
    ]
    parts = ["<p><b>Compliance action raised by Xposure</b></p>", "<ul>"]
    for key, value in rows:
        parts.append(f"<li><b>{escape(key)}:</b> {escape(clean(str(value)))}</li>")
    parts.append("</ul>")
    if summary_en:
        parts.append(f"<p>{escape(summary_en)}</p>")
    if summary_ar:
        parts.append(f'<p dir="rtl">{escape(summary_ar)}</p>')
    if note and note.strip():
        parts.append(f"<p><b>Note from the reviewer:</b> {escape(clean(note.strip()))}</p>")
    parts.append(
        f'<p><b>Details in Xposure:</b> <a href="{escape(link, quote=True)}">{escape(link)}</a></p>'
    )
    parts.append(
        "<p>Move the card to Waiting for Confirmation when the work is done and to Done once it is "
        "verified. Xposure reads the stage back.</p>"
    )

    return {
        "name": name,
        "description_html": "".join(parts),
        "due_date": due,
        "important": band in ("critical", "high"),
        "change_title": change_title,
        "clause_ref": str(clause_ref),
        "priority": priority,
        "link": link,
    }
