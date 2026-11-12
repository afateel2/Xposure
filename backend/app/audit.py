"""
Append-only audit trail (`audit_log`).

Every node of the M6 agent loop writes here — that is a hard guardrail from
the takeoff prompt (section 3/M6 and section 7), not optional polish: the
whole point of an agent that touches compliance data is that a human can
reconstruct, after the fact, exactly what it looked at, what it decided,
and on what basis. This module exists so no node has to hand-roll that,
and so "what an audit row looks like" has one definition instead of eight
slightly different ones.

Two deliberate choices worth knowing about:

1. `record()` COMMITS by default. The audit row is written in the caller's
   session, so committing here also commits whatever else that node had
   pending — which is exactly what the nodes want (do the work, then
   record that the work happened, in one transaction: either both landed
   or neither did). What must never happen is an audit row that claims
   work happened when the work rolled back, so the row and the work share
   a transaction rather than being written independently.

2. `record_in_new_session()` exists for the one case where the caller's
   session cannot be trusted: the failure path. If a node raised, its
   session is very likely in a failed-transaction state, and the whole
   point of recording the failure is that it must survive. So the failure
   record opens its own session.

Rows here are append-only: nothing in this codebase updates or deletes an
AuditLog row, and nothing should. A correction is a new row, not an edit.
"""

from typing import Any

from sqlalchemy.orm import Session

from .db.models import AuditLog
from .db.session import get_engine


def node_actor(node_name: str) -> str:
    """Actor string for an agent-loop node, e.g. "agent:diff_node".

    Matches the convention documented on AuditLog.actor in db/models.py.
    Human actors use "user:<id>" instead; those rows are written by the
    API layer (M7), not from here."""
    return f"agent:{node_name}_node"


def record(
    db: Session,
    actor: str,
    event: str,
    ref_type: str = "",
    ref_id: int | None = None,
    payload: dict[str, Any] | None = None,
    commit: bool = True,
) -> AuditLog:
    """Append one audit row.

    `ref_type`/`ref_id` point at the row this event is about ("change",
    "action", "regulation_version", ...) — deliberately a loose
    type+id pair rather than a real FK, because audit rows reference
    several different tables and some events (a whole run, a source-file
    scan) reference no table row at all.

    `payload` must be JSON-serializable: it goes into a JSON column, and a
    non-serializable value fails at commit time rather than being silently
    coerced."""
    entry = AuditLog(
        actor=actor,
        event=event,
        ref_type=ref_type,
        ref_id=ref_id,
        payload_json=payload or {},
    )
    db.add(entry)
    if commit:
        db.commit()
    else:
        db.flush()
    return entry


def record_in_new_session(
    actor: str,
    event: str,
    ref_type: str = "",
    ref_id: int | None = None,
    payload: dict[str, Any] | None = None,
) -> int:
    """Append one audit row in a fresh session, returning its id.

    For callers whose own session may be unusable — chiefly the agent
    runner's failure path, where a node has just raised and left its
    transaction in a failed state. Recording a failure must not itself
    depend on the thing that failed."""
    with Session(get_engine()) as db:
        entry = record(db, actor, event, ref_type=ref_type, ref_id=ref_id, payload=payload)
        return entry.id
