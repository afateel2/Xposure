"""
Remove the Odoo tasks Xposure created, as part of the demo reset.

A demo take can end with real tasks in Odoo (the "escalate through the ERP"
flow). Resetting only the Xposure database would leave them behind, so the
next take would start with stale tasks in the ERP. This deletes exactly the
tasks Xposure knows it created and nothing else:

  - the ids come from Action.payload_json["erp"]["task_id"] and from every
    entry of Action.payload_json["erp_detached"] (a delegation that was
    undone), read BEFORE the actions are deleted;
  - OdooService.delete_task() only deletes a task that still exists AND sits
    in the configured Xposure project, so an id that Odoo reused for something
    else is never touched.

Best effort by design. It must never fail the reset and never make it slow:
no task ids means no Odoo call at all; otherwise short HTTP timeouts and a
hard overall deadline apply, and every error is swallowed into the result:

    {"deleted": N, "referenced": M, "already_gone": K, "skipped_reason": "..."?}

`skipped_reason` appears only when the cleanup could not finish (Odoo not
configured, unreachable, timed out, or an API error); the tasks it did not
reach are then left in Odoo, and the result says so.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Action
from ..erp.client import ErpError, OdooClient
from ..erp.service import OdooService
from ..erp.settings import get_erp_settings

log = logging.getLogger(__name__)

CONNECT_TIMEOUT = 2.0
READ_TIMEOUT = 5.0
#: Hard cap on the whole cleanup, so a slow Odoo cannot slow the reset by more than this.
DEADLINE_SECONDS = 8.0


def collect_task_ids(db: Session) -> list[int]:
    """Every Odoo task id Xposure recorded on an action (current and detached)."""
    ids: set[int] = set()
    for payload in db.scalars(select(Action.payload_json)):
        if not isinstance(payload, dict):
            continue
        entries: list[Any] = [payload.get("erp")]
        detached = payload.get("erp_detached")
        if isinstance(detached, list):
            entries.extend(detached)
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            try:
                task_id = entry.get("task_id")
                if task_id is not None:
                    ids.add(int(task_id))
            except (TypeError, ValueError):
                continue
    return sorted(ids)


def _delete_all(task_ids: list[int], result: dict[str, Any]) -> None:
    """Runs in a worker thread and records progress in `result` as it goes,
    so a deadline hit still reports what was already deleted."""
    settings = get_erp_settings()
    try:
        client = OdooClient(settings, connect_timeout=CONNECT_TIMEOUT, read_timeout=READ_TIMEOUT)
    except ErpError as exc:  # not configured
        result["skipped_reason"] = f"{exc.kind}: {exc.message_en}"
        return
    service = OdooService(client, settings)
    with client:
        for task_id in task_ids:
            try:
                if service.delete_task(task_id):
                    result["deleted"] += 1
                else:
                    result["already_gone"] += 1
            except ErpError as exc:
                result["skipped_reason"] = f"{exc.kind}: {exc.message_en}"
                return


def clear_erp_tasks(task_ids: list[int]) -> dict[str, Any]:
    """Delete the given tasks from Odoo, best effort. Never raises."""
    result: dict[str, Any] = {"deleted": 0, "referenced": len(task_ids), "already_gone": 0}
    if not task_ids:
        return result

    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="demo-erp-cleanup")
    future = pool.submit(_delete_all, task_ids, result)
    try:
        future.result(timeout=DEADLINE_SECONDS)
    except FutureTimeout:
        result["skipped_reason"] = f"timeout: Odoo did not finish within {DEADLINE_SECONDS:.0f} s"
    except Exception as exc:  # anything at all: the reset must not fail over the ERP
        log.warning("erp cleanup failed: %s: %s", type(exc).__name__, exc)
        result["skipped_reason"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    finally:
        pool.shutdown(wait=False)  # never wait on a stuck call
    return dict(result)
