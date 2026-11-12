"""
Derived per-node status for the Facility profile: for every org node, what
the company documents and the action queue say about it right now.

Nothing here is stored. Status is computed on each request from three facts
that already exist: the node's actions (through their Impact row), whether an
action carries a live file effect, and the mapped file's version history.

Status precedence, highest first (a node gets exactly one):

  updated_by_agent  at least one of its actions has a live (not undone) file edit
  assigned          at least one of its actions was delegated and awaits confirmation
  action_required   at least one of its actions is still pending a human decision
  up_to_date        nothing open

`updated_by_agent` outranks `action_required` on purpose: a policy touched by
many changes always has some other pending action, and the point of the badge
is to show that the agent DID edit this document. The remaining open work is
reported next to it in `open_action_count`.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Action, Impact, OrgEdge, OrgNode
from . import store

STATUS_LABELS = {
    "up_to_date": ("Up to date", "محدّث"),
    "action_required": ("Action required", "يتطلب إجراءً"),
    "assigned": ("Assigned", "مُسنَد"),
    "updated_by_agent": ("Updated by agent", "عُدِّل بواسطة الوكيل"),
}

TYPE_LABELS = {
    "product": ("Product", "منتج"),
    "process": ("Process", "عملية"),
    "policy": ("Policy", "سياسة"),
    "procedure": ("Procedure", "إجراء"),
    "evidence": ("Evidence", "دليل إثبات"),
    "owner": ("Owner", "مسؤول"),
    "supplier": ("Supplier", "مورّد"),
    "site": ("Site", "موقع"),
    "control_mapping": ("Control", "ضابط"),
}


def node_display_type(node: OrgNode) -> str:
    """`procedure` for a policy-type node marked doc_type: procedure, else the node type."""
    attrs = node.attrs_json or {}
    if node.type == "policy" and attrs.get("doc_type") == "procedure":
        return "procedure"
    return node.type


def action_node_ids(db: Session) -> tuple[list[Action], dict[int, int]]:
    """(all actions, action id -> impacted node id)."""
    impacts = {i.id: i.node_id for i in db.scalars(select(Impact))}
    actions = list(db.scalars(select(Action).order_by(Action.id)))
    mapping: dict[int, int] = {}
    for action in actions:
        payload = action.payload_json or {}
        node_id = payload.get("impact_node_id")
        if node_id is None:
            node_id = impacts.get(payload.get("impact_id"))
        if node_id is not None:
            mapping[action.id] = node_id
    return actions, mapping


def derive_status(*, has_live_effect: bool, assigned: int, open_count: int) -> str:
    if has_live_effect:
        return "updated_by_agent"
    if assigned:
        return "assigned"
    if open_count:
        return "action_required"
    return "up_to_date"


def build_nodes(db: Session, *, include_controls: bool = False) -> list[dict[str, Any]]:
    nodes = list(db.scalars(select(OrgNode).order_by(OrgNode.id)))
    nodes_by_id = {n.id: n for n in nodes}
    edges = list(db.scalars(select(OrgEdge).order_by(OrgEdge.id)))
    impacts = list(db.scalars(select(Impact).order_by(Impact.id)))
    actions, node_of_action = action_node_ids(db)
    files = {f["path"]: f for f in store.list_files()}

    owner_of: dict[int, OrgNode] = {}
    for edge in edges:
        if edge.relation == "owned_by" and edge.from_id not in owner_of:
            owner = nodes_by_id.get(edge.to_id)
            if owner is not None and owner.type == "owner":
                owner_of[edge.from_id] = owner

    changes_of: dict[int, set[int]] = {}
    for impact in impacts:
        changes_of.setdefault(impact.node_id, set()).add(impact.change_id)

    actions_of: dict[int, list[Action]] = {}
    for action in actions:
        node_id = node_of_action.get(action.id)
        if node_id is not None:
            actions_of.setdefault(node_id, []).append(action)

    out: list[dict[str, Any]] = []
    for node in nodes:
        if node.type == "control_mapping" and not include_controls:
            continue
        attrs = node.attrs_json or {}
        node_actions = actions_of.get(node.id, [])
        pending = [a for a in node_actions if a.status == "pending"]
        assigned = [a for a in node_actions if a.status == "awaiting_confirmation"]
        live_effects = [(a.payload_json or {}).get("effect") for a in node_actions if isinstance((a.payload_json or {}).get("effect"), dict)]
        status = derive_status(has_live_effect=bool(live_effects), assigned=len(assigned), open_count=len(pending))
        path = attrs.get("file") or attrs.get("config_file")
        file_info = files.get(str(path)) if path else None
        owner = owner_of.get(node.id)
        display_type = node_display_type(node)
        type_en, type_ar = TYPE_LABELS.get(display_type, (display_type, display_type))
        label_en, label_ar = STATUS_LABELS[status]
        out.append({
            "id": node.id,
            "type": node.type,
            "display_type": display_type,
            "type_label_en": type_en,
            "type_label_ar": type_ar,
            "name": node.name,
            "attrs": attrs,
            "owner": (
                {"id": owner.id, "name": owner.name, "email": (owner.attrs_json or {}).get("email"), "role": (owner.attrs_json or {}).get("role")}
                if owner else None
            ),
            "file": attrs.get("file"),
            "config_file": attrs.get("config_file"),
            "path": path,
            "version": file_info["version"] if file_info else None,
            "last_modified": file_info["last_modified"] if file_info else None,
            "last_origin": file_info["last_origin"] if file_info else None,
            "status": status,
            "status_label_en": label_en,
            "status_label_ar": label_ar,
            "open_action_count": len(pending),
            "assigned_action_count": len(assigned),
            "agent_edit_count": len(live_effects),
            "last_agent_edit": max((e.get("executed_at") or "" for e in live_effects), default=None) or None,
            "change_ids": sorted(changes_of.get(node.id, set())),
            "open_change_ids": sorted({a.change_id for a in pending}),
        })
    return out


def count_open_actions(db: Session) -> dict[str, int]:
    actions = list(db.scalars(select(Action)))
    return {
        "pending": sum(1 for a in actions if a.status == "pending"),
        "assigned": sum(1 for a in actions if a.status == "awaiting_confirmation"),
    }
