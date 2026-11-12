"""
GET /agent/suggestions and POST /agent/command_preview — the "agent control
pad" backend: a UI surface where a user clicks a canned suggestion or types
free text like "approve the clarification changes for ECC 2-5", and gets
back a PREVIEW of which changes/actions that text refers to and what
decision (if any) it looks like was requested. Nothing here executes
anything. The frontend is expected to hand a confirmed
matched_action_ids/proposed_decision pair straight to the existing, fully
audited POST /actions/bulk (routes/actions.py) after a human looks at the
preview — this module never calls that endpoint itself.

The matcher is deterministic keyword/entity matching, not an LLM call, on
purpose: an LLM asked to "interpret" free text into a set of action ids
would be a second, less-auditable path that can steer a real bulk action,
sitting next to the one path (routes/actions.py) that already is fully
audited. A keyword matcher's failure mode is "matched nothing" for a
command a human would understand; an LLM's failure mode can be "matched the
wrong rows with total confidence." The former is safe and annoying; the
latter is unsafe. So this only ever ANDs together signals it can point to
explicitly, and a command with no recognized signal returns empty lists,
never "everything" — that is the actual safety property of this endpoint,
not a side effect of how it happens to be implemented.
"""

import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Action, Change, Regulation, Regulator
from ..db.session import get_db
from ..llm import CHANGE_TYPES

router = APIRouter(tags=["agent_console"])


SUGGESTIONS = [
    {
        "id": "summarize-critical",
        "text_en": "Summarize highest-priority changes",
        "text_ar": "لخّص التغييرات ذات الأولوية القصوى",
    },
    {
        "id": "summarize-overdue",
        "text_en": "Summarize overdue actions",
        "text_ar": "لخّص الإجراءات المتأخرة عن موعدها",
    },
    {
        "id": "list-clarifications",
        "text_en": "List all clarification changes",
        "text_ar": "اعرض جميع التغييرات التوضيحية",
    },
    {
        "id": "list-new-obligations",
        "text_en": "List new obligation changes",
        "text_ar": "اعرض التغييرات التي تمثل التزامات جديدة",
    },
    {
        "id": "summarize-tightened",
        "text_en": "Summarize tightened requirements",
        "text_ar": "لخّص المتطلبات التي زادت صرامتها",
    },
]


class CommandPreviewRequest(BaseModel):
    command: str


# change_type (from CHANGE_TYPES, underscores -> spaces) plus small, explicit
# synonym set. Kept intentionally short (per the task: "don't get clever") —
# an unmatched synonym just falls through to "no change-type signal", which
# is the safe direction to fail in.
_CHANGE_TYPE_SYNONYMS: dict[str, str] = {
    "clarifications": "clarification",
    "clarify": "clarification",
    "tightening": "tightened",
    "tighten": "tightened",
    "relaxation": "relaxed",
    "relaxations": "relaxed",
    "relax": "relaxed",
    "new obligations": "new obligation",
    "withdrawals": "withdrawn",
    "withdrawal": "withdrawn",
    "renumbering": "renumbered",
}

_BAND_PHRASES: dict[str, frozenset[str]] = {
    "highest priority": frozenset({"critical", "high"}),
    "high priority": frozenset({"high"}),
    "critical": frozenset({"critical"}),
    "medium": frozenset({"medium"}),
    "low priority": frozenset({"low"}),
}

# Real seeded data has only one regulator/regulation (nca/ecc) — see the
# task's note not to over-engineer this for a multi-regulator future with
# no data to test against yet.
_KNOWN_REGULATOR_KEYWORDS = {"nca"}
_KNOWN_REGULATION_KEYWORDS = {"ecc"}

# Shaped like this app's real clause ids (e.g. "2-5-3-9", "2.14.3.5"):
# digits, then one or more "-" or "." separated digit groups. Requires at
# least one separator so a lone number ("30" as in "30 days") never matches
# as a clause reference.
_CLAUSE_ID_RE = re.compile(r"\b\d+(?:[-.]\d+)+\b")

_VERB_APPROVE = ("approve", "approved")
_VERB_DISMISS = ("dismiss", "reject", "decline")
_VERB_SUMMARIZE = ("summarize", "summary", "list", "show")

CONFIDENCE_PER_SIGNAL = 0.25
CONFIDENCE_CAP = 0.95


def _match_change_type(command_lower: str) -> str | None:
    for change_type in CHANGE_TYPES:
        if change_type.replace("_", " ") in command_lower:
            return change_type
    for phrase, change_type in _CHANGE_TYPE_SYNONYMS.items():
        if phrase in command_lower:
            return change_type
    return None


def _match_bands(command_lower: str) -> frozenset[str] | None:
    # "highest priority"/"high priority" both contain "high priority" as a
    # substring only for the former's synonym; check the more specific
    # phrase first so "highest priority" doesn't get shadowed by "high".
    for phrase in ("highest priority", "high priority", "critical", "medium", "low priority"):
        if phrase in command_lower:
            return _BAND_PHRASES[phrase]
    return None


def _match_regulator_regulation(command_lower: str) -> str | None:
    for keyword in _KNOWN_REGULATOR_KEYWORDS | _KNOWN_REGULATION_KEYWORDS:
        if keyword in command_lower:
            return keyword
    return None


def _match_verb(command_lower: str) -> str | None:
    if any(v in command_lower for v in _VERB_APPROVE):
        return "approve"
    if any(v in command_lower for v in _VERB_DISMISS):
        return "dismiss"
    if any(v in command_lower for v in _VERB_SUMMARIZE):
        return "summarize"
    return None


def _explanation(
    matched_count: int,
    change_type: str | None,
    bands: frozenset[str] | None,
    clause_ids: list[str],
    regulator_regulation: str | None,
    decision: str | None,
) -> tuple[str, str]:
    if matched_count == 0:
        return (
            "No changes matched the given text: no band, change type, clause reference, or regulator keyword was recognized.",
            "لم يتطابق أي تغيير مع النص المُدخل، إذ لم يُعثر على أي إشارة إلى مستوى أولوية أو نوع تغيير أو رقم بند أو جهة تنظيمية.",
        )
    signal_parts_en = []
    signal_parts_ar = []
    if change_type:
        signal_parts_en.append(f"change_type={change_type}")
        signal_parts_ar.append(f"نوع التغيير={change_type}")
    if bands:
        signal_parts_en.append(f"band={'/'.join(sorted(bands))}")
        signal_parts_ar.append(f"مستوى الأولوية={'/'.join(sorted(bands))}")
    if clause_ids:
        signal_parts_en.append(f"clause={'/'.join(clause_ids)}")
        signal_parts_ar.append(f"البند={'/'.join(clause_ids)}")
    if regulator_regulation:
        signal_parts_en.append(f"regulator/regulation={regulator_regulation}")
        signal_parts_ar.append(f"الجهة/اللائحة={regulator_regulation}")

    en = f"Matched {matched_count} change(s): " + ", ".join(signal_parts_en) + "."
    ar = f"تم مطابقة {matched_count} تغييرًا: " + "، ".join(signal_parts_ar) + "."

    if decision == "approve":
        en += " Approve verb detected: these matches are candidates for bulk approval."
        ar += " تم رصد لفظ الموافقة، وهذه المطابقات مرشحة للموافقة الجماعية."
    elif decision == "dismiss":
        en += " Dismiss verb detected: these matches are candidates for bulk dismissal."
        ar += " تم رصد لفظ الرفض، وهذه المطابقات مرشحة للرفض الجماعي."
    elif decision == "summarize":
        en += " Summarize/list intent detected: read-only, not an actionable decision."
        ar += " تم رصد نية عرض أو تلخيص، وهي للاطلاع فقط وليست قرارًا قابلاً للتنفيذ."
    else:
        en += " No action verb detected: showing matches only."
        ar += " لم يُرصد أي فعل إجرائي، ويُعرض التطابق فقط دون قرار."

    return en, ar


@router.get("/agent/suggestions")
def get_suggestions():
    return SUGGESTIONS


@router.post("/agent/command_preview")
def command_preview(body: CommandPreviewRequest, db: Session = Depends(get_db)):
    command_lower = body.command.lower()

    change_type = _match_change_type(command_lower)
    bands = _match_bands(command_lower)
    clause_ids = _CLAUSE_ID_RE.findall(body.command)
    regulator_regulation = _match_regulator_regulation(command_lower)
    verb = _match_verb(command_lower)
    proposed_decision = verb  # "approve" | "dismiss" | "summarize" | None — same vocabulary either way

    # Scoping signals are the ones that narrow which rows the query below
    # touches; the verb alone narrows nothing. A verb-only command (e.g.
    # just "approve") must NOT fall through to an unscoped `select(Change)`
    # that would silently match every row in the table — that is exactly
    # the "matched everything" failure mode this module's docstring says
    # can never happen. Confirmed as a real gap by testing it, not just
    # reasoning about it: "approve" alone returned all 5 seeded changes
    # before this guard was added.
    scoping_signals = (change_type, bands, clause_ids, regulator_regulation)
    signal_count = sum(1 for signal in (*scoping_signals, verb) if signal)

    if not any(scoping_signals):
        if verb is not None:
            explanation_en = (
                f"A {verb!r} instruction was recognized, but nothing scopes which changes it applies "
                "to: add a change type, priority level, clause number, or regulator. Refusing to match "
                "every change by default."
            )
            explanation_ar = (
                f"تم رصد فعل إجرائي ({verb})، لكن لا توجد إشارة تحدد التغييرات المقصودة، مثل نوع التغيير "
                "أو مستوى الأولوية أو رقم البند أو الجهة التنظيمية. تم الامتناع عن مطابقة كل التغييرات "
                "افتراضيًا."
            )
        else:
            explanation_en, explanation_ar = _explanation(0, None, None, [], None, None)
        return {
            "matched_change_ids": [],
            "matched_action_ids": [],
            "proposed_decision": None,
            "confidence": 0.0,
            "explanation_en": explanation_en,
            "explanation_ar": explanation_ar,
        }

    stmt = select(Change)
    if change_type is not None:
        stmt = stmt.where(Change.change_type == change_type)
    if clause_ids:
        clause_filters = [
            (Change.old_clause_id == cid) | (Change.new_clause_id == cid) for cid in clause_ids
        ]
        combined = clause_filters[0]
        for extra in clause_filters[1:]:
            combined = combined | extra
        stmt = stmt.where(combined)
    if regulator_regulation is not None:
        stmt = stmt.join(Regulation, Regulation.id == Change.regulation_id).join(
            Regulator, Regulator.id == Regulation.regulator_id
        ).where(
            (Regulation.code == regulator_regulation) | (Regulator.code == regulator_regulation)
        )

    changes = list(db.scalars(stmt))

    if bands is not None:
        from .changes import compute_priority_for_change

        filtered = []
        for change in changes:
            if change.change_type is None:
                continue
            _score, band = compute_priority_for_change(db, change)
            if band in bands:
                filtered.append(change)
        changes = filtered

    matched_change_ids = [c.id for c in changes]

    matched_action_ids: list[int] = []
    if matched_change_ids:
        matched_action_ids = list(
            db.scalars(
                select(Action.id).where(
                    Action.change_id.in_(matched_change_ids), Action.status == "pending"
                )
            )
        )

    confidence = min(CONFIDENCE_CAP, CONFIDENCE_PER_SIGNAL * signal_count)

    explanation_en, explanation_ar = _explanation(
        len(matched_change_ids), change_type, bands, clause_ids, regulator_regulation, proposed_decision
    )

    return {
        "matched_change_ids": matched_change_ids,
        "matched_action_ids": matched_action_ids,
        "proposed_decision": proposed_decision,
        "confidence": confidence,
        "explanation_en": explanation_en,
        "explanation_ar": explanation_ar,
    }
