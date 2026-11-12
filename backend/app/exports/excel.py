"""
Excel export, per change: an .xlsx sheet shaped like the NCA ECC
self-assessment spreadsheet `app/adapters/org/csv_assessment.py` already
knows how to read back in (control_id, status, owner, evidence_ref) —
takeoff prompt section 3/M8, "impacted rows only".

"Impacted rows" means the change's impacted `control_mapping` nodes
specifically, not every impacted node: a control_mapping IS one row of a
real self-assessment sheet (that adapter's own docstring: one CSV row
becomes one control_mapping node, optionally edged to an owner and
evidence). Impacted process/policy/product/etc. nodes downstream of that
control are a different kind of fact ("who else is affected"), already
covered by the PDF/JSON exports' impacted-nodes section — putting them in
this sheet would produce rows with no real control_id, which is exactly
the "column that isn't really a control id" failure mode
csv_assessment.py's docstring says is a loud-failure case on import, not
something to manufacture on export.

status is not the organization's actual assessed compliance status (this
export has no access to that — the self-assessment sheet is the org's own
record, not derived data); it is what this regulatory change now requires
of that row, so a compliance officer can drop this sheet into their
existing tracker as a worklist rather than a duplicate of data already
being tracked elsewhere.
"""

from datetime import date
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Change, Impact, OrgEdge, OrgNode

_HEADERS = ["control_id", "status", "owner", "evidence_ref", "note"]
_STATUS_LABEL = {
    "reassess_control": "Reassess (regulatory change)",
    "update_policy": "Update governing policy",
    "update_procedure": "Update procedure",
    "collect_evidence": "Collect new evidence",
    "technical_change": "Technical change required",
    "notify_owner": "Notify owner",
    "request_license_review": "Request license review",
}


def _status_for(recommended_actions: list[str]) -> str:
    for action_type in ("reassess_control", "update_policy", "update_procedure", "technical_change"):
        if action_type in recommended_actions:
            return _STATUS_LABEL[action_type]
    if recommended_actions:
        return _STATUS_LABEL.get(recommended_actions[0], recommended_actions[0])
    return "Review"


def _owner_and_evidence(db: Session, node_id: int) -> tuple[str, str]:
    """Same edge vocabulary csv_assessment.py's docstring documents:
    control_mapping --owned_by--> owner, --evidenced_by--> evidence
    (evidence's real-world reference lives in attrs_json["ref"])."""
    edges = list(db.scalars(select(OrgEdge).where(OrgEdge.from_id == node_id)))
    owner = ""
    evidence_ref = ""
    for edge in edges:
        target = db.get(OrgNode, edge.to_id)
        if target is None:
            continue
        if edge.relation == "owned_by":
            owner = target.name
        elif edge.relation == "evidenced_by":
            evidence_ref = str((target.attrs_json or {}).get("ref", target.name))
    return owner, evidence_ref


def build_assessment_workbook(db: Session, change: Change) -> bytes:
    """Returns .xlsx bytes for one change's impacted control-mapping rows.
    A change with no impacted control mappings still returns a valid
    (header-only) workbook rather than raising — an empty worklist is a
    legitimate, informative result, not an error."""
    impacts = list(
        db.scalars(
            select(Impact)
            .join(OrgNode, Impact.node_id == OrgNode.id)
            .where(Impact.change_id == change.id, OrgNode.type == "control_mapping")
            .order_by(Impact.id)
        )
    )

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Impacted controls"
    sheet.append(_HEADERS)
    for cell in sheet[1]:
        cell.font = Font(bold=True)

    for impact in impacts:
        node = db.get(OrgNode, impact.node_id)
        control_id = str((node.attrs_json or {}).get("control_id", node.name)) if node else ""
        owner, evidence_ref = _owner_and_evidence(db, impact.node_id)
        sheet.append([
            control_id,
            _status_for(impact.recommended_actions_json or []),
            owner,
            evidence_ref,
            impact.note_en,
        ])

    for column_cells in sheet.columns:
        length = max((len(str(c.value)) for c in column_cells if c.value is not None), default=10)
        sheet.column_dimensions[column_cells[0].column_letter].width = min(max(length + 2, 12), 60)

    sheet.freeze_panes = "A2"

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def workbook_filename(change: Change) -> str:
    clause = (change.new_clause_id or change.old_clause_id or str(change.id)).replace("/", "-")
    return f"xposure-change-{change.id}-{clause}-{date.today().isoformat()}.xlsx"
