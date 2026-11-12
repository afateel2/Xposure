"""
OSCAL-flavored JSON export, per change — takeoff prompt section 3/M8:
"OSCAL-flavored JSON export of the changed catalog entries".

"Flavored", deliberately, not schema-valid OSCAL: NIST's real OSCAL
catalog model (https://pages.nist.gov/OSCAL/) carries a full document
context (back-matter, resolved profiles, a complete control catalog) that
Xposure has no use for and no source of — inventing a UUID-laden fake
catalog around one control to satisfy a validator would create the exact
kind of confident-looking fabrication the project's guardrails exist to
prevent. What's genuinely useful and genuinely OSCAL-shaped is the
`catalog.groups[].controls[].parts[]` vocabulary for the one control this
change is actually about, with its old/new statement text as two parts —
so that's what this produces, plus a clearly-separated
`xposure-change-metadata` block for everything OSCAL has no field for
(classification, confidence, source document hashes). A real OSCAL
consumer can use the `controls` array; the extension block is there for
Xposure's own round-trip, not disguised as upstream OSCAL.
"""

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from ..db.models import Change, Clause, Regulation, RegulationVersion, Regulator

OSCAL_VERSION = "1.1.2"


def _clause_text(db: Session, version_id: int | None, clause_id: str | None) -> str | None:
    if version_id is None or clause_id is None:
        return None
    from sqlalchemy import select

    clause = db.scalar(select(Clause).where(Clause.version_id == version_id, Clause.clause_id == clause_id))
    return clause.text_en if clause else None


def build_oscal_export(db: Session, change: Change) -> dict[str, Any]:
    regulator = db.get(Regulator, db.get(Regulation, change.regulation_id).regulator_id)
    regulation = db.get(Regulation, change.regulation_id)
    from_version = db.get(RegulationVersion, change.from_version_id)
    to_version = db.get(RegulationVersion, change.to_version_id)

    control_id = change.new_clause_id or change.old_clause_id
    old_text = _clause_text(db, change.from_version_id, change.old_clause_id)
    new_text = _clause_text(db, change.to_version_id, change.new_clause_id)

    parts: list[dict[str, Any]] = []
    if old_text is not None:
        parts.append({"name": "statement", "prop-name": "previous-text", "prose": old_text})
    if new_text is not None:
        parts.append({"name": "statement", "prop-name": "current-text", "prose": new_text})

    catalog: dict[str, Any] = {
        "metadata": {
            "title": f"{regulation.title_en}: changed control {control_id}",
            "oscal-version": OSCAL_VERSION,
            "last-modified": datetime.now(timezone.utc).isoformat(),
            "version": to_version.version_label if to_version else (from_version.version_label if from_version else "unknown"),
            "parties": [{"party-uuid": regulator.code, "type": "organization", "name": regulator.name_en}],
        },
        "groups": [
            {
                "id": regulation.code,
                "title": regulation.title_en,
                "controls": [
                    {
                        "id": control_id,
                        "title": f"{regulator.code.upper()} {control_id}",
                        "props": [
                            {"name": "change-type", "value": change.change_type},
                            {"name": "match-kind", "value": change.match_kind},
                            {"name": "material", "value": str(bool(change.material)).lower()},
                        ],
                        "parts": parts,
                    }
                ],
            }
        ],
    }

    return {
        "catalog": catalog,
        "xposure-change-metadata": {
            "note": "Not part of the OSCAL catalog model above; Xposure-specific fields for round-tripping this export.",
            "change_id": change.id,
            "old_clause_id": change.old_clause_id,
            "new_clause_id": change.new_clause_id,
            "confidence": change.confidence,
            "summary_en": change.summary_en,
            "summary_ar": change.summary_ar,
            "effective_date": change.effective_date.isoformat() if change.effective_date else None,
            "grace_days": change.grace_days,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "source_documents": [
                doc
                for doc in (
                    {
                        "version_label": from_version.version_label,
                        "sha256": from_version.file_sha256,
                    }
                    if from_version else None,
                    {
                        "version_label": to_version.version_label,
                        "sha256": to_version.file_sha256,
                    }
                    if to_version else None,
                )
                if doc is not None
            ],
        },
    }


def oscal_filename(change: Change) -> str:
    clause = (change.new_clause_id or change.old_clause_id or str(change.id)).replace("/", "-")
    return f"xposure-change-{change.id}-{clause}-{date.today().isoformat()}.oscal.json"
