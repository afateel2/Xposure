"""
Company workspace API: the demo company's profile, its org nodes with a
derived status, and its versioned documents.

  GET  /company                        profile plus counts
  GET  /company/nodes                  org nodes with derived status
  GET  /company/files                  every managed file
  GET  /company/files/{path}           one file: content, versions, diff of the last two
  POST /company/files/{path}/revert    restore the previous version as a new version

Files live in the sandboxed workspace (app/company/store.py). Reads are
free; the only writes here are the manual revert, and the agent's own edits,
which happen through POST /actions/{id}/approve (routes/actions.py).
"""

from __future__ import annotations

import difflib
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..auth import require_user
from ..company import nodes as company_nodes
from ..company import store
from ..db.models import Action, AppUser, OrgNode, Regulation, RegulationVersion
from ..db.session import get_db

router = APIRouter(tags=["company"])


def _raise_http(exc: store.CompanyStoreError) -> None:
    if isinstance(exc, store.UnsafePathError):
        raise HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, store.FileNotInCompanyError):
        raise HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, store.NothingToRevertError):
        raise HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, store.InvalidContentError):
        raise HTTPException(status_code=422, detail=str(exc))
    raise HTTPException(status_code=500, detail=str(exc))


def _known_regulation_versions(db: Session) -> list[str]:
    rows = db.execute(
        select(Regulation.code, RegulationVersion.version_label)
        .join(RegulationVersion, RegulationVersion.regulation_id == Regulation.id)
        .order_by(RegulationVersion.id)
    ).all()
    return [f"{code.upper()}-{label.replace('-', ':')}" for code, label in rows]


@router.get("/company")
def get_company(db: Session = Depends(get_db)):
    try:
        profile = store.load_profile()
        files = store.list_files()
    except store.CompanyStoreError as exc:
        _raise_http(exc)
    node_list = company_nodes.build_nodes(db)
    open_actions = company_nodes.count_open_actions(db)
    return {
        "profile": profile,
        "applied_regulation": profile.get("applied_regulation"),
        "known_regulation_versions": _known_regulation_versions(db),
        "counts": {
            "files": len(files),
            "nodes": len(node_list),
            "open_actions": open_actions["pending"],
            "assigned_actions": open_actions["assigned"],
            "agent_edited_files": sum(1 for f in files if f["agent_edited"]),
        },
    }


@router.get("/company/nodes")
def list_company_nodes(include_controls: bool = False, db: Session = Depends(get_db)):
    """Org nodes with derived status. Control mappings are graph plumbing and are left out unless asked for."""
    try:
        node_list = company_nodes.build_nodes(db, include_controls=include_controls)
    except store.CompanyStoreError as exc:
        _raise_http(exc)
    by_status: dict[str, int] = {}
    for node in node_list:
        by_status[node["status"]] = by_status.get(node["status"], 0) + 1
    return {"nodes": node_list, "counts_by_status": by_status}


@router.get("/company/files")
def list_company_files():
    try:
        return {"files": store.list_files()}
    except store.CompanyStoreError as exc:
        _raise_http(exc)


def _diff_between(rel: str, versions: list[dict[str, Any]], index: int) -> dict[str, Any] | None:
    """Unified diff between versions[index - 1] and versions[index]; None for the first version."""
    if index < 1:
        return None
    before, after = versions[index - 1], versions[index]
    old = store.read_version(rel, before["n"])
    new = store.read_version(rel, after["n"])
    old_lines, new_lines = old.splitlines(), new.splitlines()
    added = removed = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old_lines, new_lines).get_opcodes():
        if tag in ("replace", "delete"):
            removed += i2 - i1
        if tag in ("replace", "insert"):
            added += j2 - j1
    unified = "\n".join(difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"{rel} (v{before['doc_version']})", tofile=f"{rel} (v{after['doc_version']})", lineterm="", n=2,
    ))
    return {
        "from_n": before["n"], "to_n": after["n"],
        "from_version": before["doc_version"], "to_version": after["doc_version"],
        "added": added, "removed": removed, "unified": unified,
    }


def _file_detail(db: Session, rel: str, version: int | None = None) -> dict[str, Any]:
    info = store.file_info(rel)
    rel = info["path"]
    versions = store.get_versions(rel)
    index = len(versions) - 1
    if version is not None:
        matches = [i for i, v in enumerate(versions) if v["n"] == version]
        if not matches:
            raise HTTPException(status_code=404, detail=f"{rel} has no version {version}")
        index = matches[0]
    content = store.read_file(rel) if index == len(versions) - 1 else store.read_version(rel, versions[index]["n"])
    mapped = [
        {"id": n.id, "name": n.name, "type": n.type}
        for n in db.scalars(select(OrgNode).order_by(OrgNode.id))
        if rel in ((n.attrs_json or {}).get("file"), (n.attrs_json or {}).get("config_file"))
    ]
    return {
        **info,
        "content": content,
        "content_version_n": versions[index]["n"],
        "versions": versions,
        "diff": _diff_between(rel, versions, index),
        "nodes": mapped,
    }


@router.get("/company/files/{path:path}")
def get_company_file(path: str, version: int | None = None, db: Session = Depends(get_db)):
    try:
        return _file_detail(db, path, version)
    except store.CompanyStoreError as exc:
        _raise_http(exc)


@router.post("/company/files/{path:path}/revert")
def revert_company_file(path: str, db: Session = Depends(get_db), user: AppUser = Depends(require_user)):
    """Restore the version before the latest one, as a new version (history is append-only)."""
    try:
        before = store.get_versions(path)
        entry = store.revert_to_previous(path)
    except store.CompanyStoreError as exc:
        _raise_http(exc)
    rel = store.resolve_path(path)[0]
    restored_n = entry["reverted_to"]

    # Any action whose live file edit is now undone must stop claiming it.
    marked: list[int] = []
    for action in db.scalars(select(Action)):
        effect = (action.payload_json or {}).get("effect")
        if isinstance(effect, dict) and effect.get("path") == rel and effect.get("history_after", 0) > restored_n:
            payload = {k: v for k, v in (action.payload_json or {}).items() if k != "effect"}
            action.payload_json = {
                **payload,
                "effect_reverted": {**effect, "reverted_at": entry["timestamp"], "history_reverted": entry["n"], "reverted_by": "file_revert"},
            }
            marked.append(action.id)

    audit.record(
        db, actor=user.actor(), event="company_file_reverted", ref_type="company_file",
        payload={"path": rel, "restored_history_n": restored_n, "new_history_n": entry["n"], "from_history_n": before[-1]["n"], "actions_marked": marked},
    )
    return {**_file_detail(db, rel), "reverted_to_n": restored_n, "actions_marked": marked}
