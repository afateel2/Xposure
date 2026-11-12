"""CsvAssessmentSheetAdapter — the NCA ECC self-assessment spreadsheet.

This is how a real customer seeds the graph (takeoff prompt section 3/M4):
almost every KSA entity subject to ECC already maintains a self-assessment
workbook mapping each control reference number to a compliance status, an
owning department and a pointer to the evidence. That single file is
already 80% of an org graph — it just has no products or processes in it.

What one row becomes:

    control_id,status,owner,evidence_ref
    2-5-3,Partially Compliant,OT Engineering,EV-NET-004

    control_mapping "ECC 2-5-3"  --owned_by-->     owner "OT Engineering"
                                 --evidenced_by--> evidence "EV-NET-004"

Owners and evidence references are deduplicated across rows (one "OT
Engineering" node, not one per control) — that is the entire point of
importing this as a graph rather than a table: after the import, "which
controls does OT Engineering own" and "which controls rest on EV-NET-004"
are one hop, and a regulatory change to any of them reaches that owner
through app.impact's traversal.

Three things this parser is deliberately tolerant about, because real
exports of this sheet are not uniform:

1. **Header naming.** Every entity renames these columns. Headers are
   normalized (lowercased, punctuation and separators collapsed) and
   matched against a synonym table that includes the Arabic headings used
   in NCA's own bilingual workbook. Only ``control_id`` is required; a
   sheet with no status/owner/evidence column still imports its control
   mappings, which is the useful minimum.

2. **Encoding.** Excel's "CSV UTF-8" export writes a BOM, and its plain
   "CSV" export on an Arabic Windows writes cp1256. Default is
   ``utf-8-sig`` (handles both UTF-8 with and without BOM); pass
   ``encoding="cp1256"`` for the latter. Guessing between them
   automatically was considered and rejected: a wrong guess produces
   plausible-looking mojibake owner names rather than an error, which is
   exactly the silent-corruption failure mode the project's guardrails
   exist to prevent.

3. **Control-id separators.** ECC-1:2018 writes "2-5-3-1", ECC-2:2024
   writes "2.5.3.1", and assessment sheets copy whichever edition they
   were built from. Both are accepted and stored verbatim in
   ``attrs["control_id"]``; app.impact matches on normalized integer
   segments, so the separator style never has to be reconciled here.

What it is NOT tolerant about (loud failure, per docs/PLAN.md section 7):
a missing control-id column, and a control id that is not a control code.
Both would silently produce a graph that looks populated but matches no
regulatory change at all.
"""

import csv
import re
from pathlib import Path
from typing import Any, ClassVar

from .base import OrgDataAdapter, OrgEdgeSpec, OrgGraphFragment, OrgNodeSpec

# Same shape ingest.py's parser recognizes as a control code: an integer,
# then 1-4 further dot/hyphen-separated integers.
_CONTROL_CODE = re.compile(r"^\d+(?:[-.]\d+){1,4}$")


def _normalize_header(header: str) -> str:
    """'Control Reference Number' / 'control_id' / 'Control-ID' -> 'controlreferencenumber' / 'controlid'."""
    return re.sub(r"[^a-z0-9؀-ۿ]+", "", header.strip().lower())


# Synonyms are stored already-normalized. Arabic entries are the headings
# used in NCA's own bilingual assessment workbook and in the Arabic column
# captions of the ECC document itself.
_COLUMN_SYNONYMS: dict[str, tuple[str, ...]] = {
    "control_id": (
        "controlid", "control", "controlno", "controlnumber", "controlcode",
        "controlreference", "controlreferencenumber", "referencenumber", "reference",
        "ecccontrol", "ecccontrolid", "clause", "clauseid",
        "رقمالضابط", "الضابط", "رمزالضابط", "الرقمالمرجعي", "الرقمالمرجعيللضابط",
    ),
    "status": (
        "status", "compliance", "compliancestatus", "compliancelevel",
        "implementationstatus", "implementationlevel", "maturity", "maturitylevel",
        "حالةالالتزام", "مستوىالالتزام", "الالتزام", "الحالة", "حالةالتطبيق",
    ),
    "owner": (
        "owner", "controlowner", "responsible", "responsibleparty", "responsibleentity",
        "department", "owningdepartment", "assignedto",
        "المالك", "مالكالضابط", "الجهةالمسؤولة", "الإدارةالمسؤولة", "المسؤول",
    ),
    "evidence_ref": (
        "evidenceref", "evidence", "evidencereference", "evidenceid",
        "artifact", "artifactref", "proof", "supportingevidence",
        "الدليل", "المرجع", "مرجعالدليل", "الأدلة", "دليلالتطبيق",
    ),
}

# NCA's four-level compliance vocabulary, normalized so M5/M6 can branch on
# it without re-parsing free text. The RAW cell value is always preserved
# alongside in attrs["status_raw"] — normalization is a convenience, not a
# replacement, and an unrecognized value maps to "unknown" rather than being
# forced into the nearest bucket.
_STATUS_SYNONYMS: dict[str, str] = {
    "compliant": "compliant",
    "fullycompliant": "compliant",
    "implemented": "compliant",
    "yes": "compliant",
    "ملتزم": "compliant",
    "مطبق": "compliant",
    "partiallycompliant": "partially_compliant",
    "partial": "partially_compliant",
    "partiallyimplemented": "partially_compliant",
    "inprogress": "partially_compliant",
    "ملتزمجزئيا": "partially_compliant",
    "مطبقجزئيا": "partially_compliant",
    "notcompliant": "not_compliant",
    "noncompliant": "not_compliant",
    "notimplemented": "not_compliant",
    "no": "not_compliant",
    "غيرملتزم": "not_compliant",
    "غيرمطبق": "not_compliant",
    "notapplicable": "not_applicable",
    "na": "not_applicable",
    "لاينطبق": "not_applicable",
}


def _slug(value: str) -> str:
    """Stable adapter-local key fragment. Arabic is kept (the ؀-ۿ
    range) rather than transliterated: an owner named only in Arabic must
    still get a distinct, reproducible key."""
    return re.sub(r"[^a-z0-9؀-ۿ]+", "_", value.strip().lower()).strip("_")


class CsvAssessmentSheetAdapter(OrgDataAdapter):
    """Reads an NCA ECC self-assessment CSV into control_mapping / owner /
    evidence nodes plus the edges between them.

    Args:
        path: the CSV file.
        encoding: see the module docstring — default handles UTF-8 with or
            without a BOM; pass "cp1256" for a plain Excel export made on
            an Arabic Windows.
        strict: if True (default), a row whose control id is not a control
            code aborts the import. If False, such rows are skipped and
            listed in ``self.skipped_rows`` — useful for a sheet that
            carries section-heading rows ("Main Domain 2") interleaved with
            real ones, which some entity-authored workbooks do.
    """

    name: ClassVar[str] = "csv_assessment"

    def __init__(self, path: Path | str, *, encoding: str = "utf-8-sig", strict: bool = True) -> None:
        self.path = Path(path)
        self.encoding = encoding
        self.strict = strict
        self.skipped_rows: list[tuple[int, str]] = []

    # ── header resolution ─────────────────────────────────────────────────

    @staticmethod
    def resolve_columns(headers: list[str]) -> dict[str, str]:
        """Map our four logical fields onto this sheet's actual header
        strings. Exposed (and static) so the mapping can be unit tested
        without a file, and so a caller can print it for a confused user.

        Raises if the required control-id column is absent, naming every
        header it did see — a sheet whose control column we cannot find is
        unusable, and saying "no control_id column" without showing what
        was there sends the user hunting blind.
        """
        by_normalized = {_normalize_header(h): h for h in headers if h is not None}
        resolved: dict[str, str] = {}
        for logical, synonyms in _COLUMN_SYNONYMS.items():
            for candidate in synonyms:
                if candidate in by_normalized:
                    resolved[logical] = by_normalized[candidate]
                    break
        if "control_id" not in resolved:
            raise ValueError(
                "This CSV has no recognizable control-id column. Headers found: "
                f"{headers}. Expected one of (case/spacing insensitive): "
                f"{', '.join(_COLUMN_SYNONYMS['control_id'][:8])}, ..."
            )
        return resolved

    @staticmethod
    def normalize_status(raw: str) -> str:
        return _STATUS_SYNONYMS.get(_normalize_header(raw), "unknown")

    # ── fetch ─────────────────────────────────────────────────────────────

    def fetch(self) -> OrgGraphFragment:
        if not self.path.is_file():
            raise FileNotFoundError(
                f"Assessment sheet not found: {self.path}\n"
                f"Export the ECC self-assessment workbook's control sheet as CSV and point --file at it."
            )

        nodes: list[OrgNodeSpec] = []
        edges: list[OrgEdgeSpec] = []
        owner_keys: dict[str, str] = {}      # owner name -> node key
        evidence_keys: dict[str, str] = {}   # evidence ref -> node key
        seen_controls: set[str] = set()
        self.skipped_rows = []

        with self.path.open(newline="", encoding=self.encoding) as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise ValueError(f"{self.path} is empty: no header row to read.")
            columns = self.resolve_columns(list(reader.fieldnames))

            for line_no, row in enumerate(reader, start=2):  # 1 = header
                control_id = (row.get(columns["control_id"]) or "").strip()
                if not control_id:
                    continue  # blank spacer row: common in hand-maintained workbooks, not an error
                if not _CONTROL_CODE.match(control_id):
                    message = (
                        f"line {line_no}: {control_id!r} is not an ECC control code "
                        f"(expected e.g. '2-5-3' or '2.5.3.1')"
                    )
                    if self.strict:
                        raise ValueError(
                            f"{self.path}, {message}. Pass strict=False to skip rows like this "
                            f"(e.g. section-heading rows) instead of failing."
                        )
                    self.skipped_rows.append((line_no, control_id))
                    continue

                if control_id in seen_controls:
                    # A duplicated control row is a real thing in merged
                    # workbooks. Keep the first; the second would otherwise
                    # collide on node key and fail validate_fragment().
                    self.skipped_rows.append((line_no, f"{control_id} (duplicate)"))
                    continue
                seen_controls.add(control_id)

                status_raw = (row.get(columns.get("status", "")) or "").strip()
                owner_raw = (row.get(columns.get("owner", "")) or "").strip()
                evidence_raw = (row.get(columns.get("evidence_ref", "")) or "").strip()

                control_key = f"cm_{control_id}"
                attrs: dict[str, Any] = {
                    "control_id": control_id,
                    "source": self.name,
                    "source_file": self.path.name,
                    "status": self.normalize_status(status_raw),
                }
                if status_raw:
                    attrs["status_raw"] = status_raw
                nodes.append(OrgNodeSpec(
                    key=control_key,
                    type="control_mapping",
                    name=f"ECC {control_id}",
                    attrs=attrs,
                ))

                if owner_raw:
                    owner_key = owner_keys.get(owner_raw)
                    if owner_key is None:
                        owner_key = f"owner_{_slug(owner_raw)}"
                        owner_keys[owner_raw] = owner_key
                        nodes.append(OrgNodeSpec(
                            key=owner_key, type="owner", name=owner_raw,
                            attrs={"source": self.name},
                        ))
                    edges.append(OrgEdgeSpec(control_key, owner_key, "owned_by"))

                if evidence_raw:
                    evidence_key = evidence_keys.get(evidence_raw)
                    if evidence_key is None:
                        evidence_key = f"evidence_{_slug(evidence_raw)}"
                        evidence_keys[evidence_raw] = evidence_key
                        nodes.append(OrgNodeSpec(
                            key=evidence_key, type="evidence", name=evidence_raw,
                            attrs={"source": self.name, "ref": evidence_raw},
                        ))
                    edges.append(OrgEdgeSpec(control_key, evidence_key, "evidenced_by"))

        if not nodes:
            raise ValueError(
                f"{self.path} produced zero org nodes: every row had a blank control id. "
                f"Check that the control column is the one this adapter resolved."
            )
        return OrgGraphFragment(nodes=nodes, edges=edges)
