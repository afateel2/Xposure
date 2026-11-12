"""
In-process state of the current or last demo scan, mirrored to the audit log.

`GET /demo/run` serves `RunTracker.snapshot()`. The live view is held in
memory (progress ticks such as "classified 57 of 208" are far too chatty
for the audit log), but every stage boundary and the run's end are ALSO
appended to audit_log (`scan_requested`, `stage_started`, `stage_completed`,
`scan_completed`, `scan_failed`, each with the run id in its payload).
That is what makes the run restart safe: if the server process ends while a
scan is running, the next request rebuilds the run from those events, finds
no terminal event and no live process behind it, appends `scan_failed`
("interrupted") and reports the run as failed. It is never reported as
still running, and never as a success it did not reach.

One run at a time: `try_start()` is atomic, a second click while a scan is
running gets the running run back instead of starting another.
"""

from __future__ import annotations

import os
import socket
import threading
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..config import settings
from ..db import session as db_session
from ..db.models import AuditLog
from . import constants as C


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def pid_alive(pid: int) -> bool:
    """Is a process with this id running? Never uses os.kill(pid, 0) on
    Windows, where signal 0 is CTRL_C_EVENT."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class DemoConflict(Exception):
    """A scan is already running (or the request is otherwise not allowed now)."""


def _blank_stage(stage: C.StageDef) -> dict[str, Any]:
    return {
        "key": stage.key,
        "label_en": stage.label_en,
        "label_ar": stage.label_ar,
        "status": "pending",
        "detail_en": "",
        "detail_ar": "",
        "counts": {},
        "started_at": None,
        "ended_at": None,
    }


def _blank_run(run_id: str | None, status: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "status": status,
        "started_at": None,
        "finished_at": None,
        "stages": [_blank_stage(s) for s in C.STAGES],
        "note_en": C.SIMULATED_PORTAL_NOTE_EN,
        "note_ar": C.SIMULATED_PORTAL_NOTE_AR,
        "thread_id": None,
        "error": None,
        "summary": {},
    }


class RunTracker:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._run: dict[str, Any] | None = None
        self._loaded = False
        self._thread: threading.Thread | None = None
        self._foreign = False  # the run belongs to another server process
        self._pacing_ms_total = 0
        self._reset_seen = 0  # id of the latest demo_reset audit row this state reflects

    # ── reads ─────────────────────────────────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        self.ensure_loaded()
        with self._lock:
            self._sync_reset()
            if self._foreign:
                self._reload()
            run = self._run if self._run is not None else _blank_run(None, "idle")
            return _copy(run)

    def is_running(self) -> bool:
        self.ensure_loaded()
        with self._lock:
            self._sync_reset()
            if self._foreign:
                self._reload()
            return self._run is not None and self._run["status"] == "running"

    @property
    def pacing_ms_total(self) -> int:
        return self._pacing_ms_total

    # ── lifecycle ─────────────────────────────────────────────────────────

    def try_start(self, run_id: str, *, actor: str = C.ACTOR_USER) -> bool:
        """Atomically begin a run. False when one is already running."""
        self.ensure_loaded()
        with self._lock:
            if self._foreign:
                self._reload()
            if self._run is not None and self._run["status"] == "running":
                return False
            run = _blank_run(run_id, "running")
            run["started_at"] = utc_iso()
            run["thread_id"] = f"demo-{run_id}"
            self._run = run
            self._foreign = False
            self._pacing_ms_total = 0
        self._audit(
            actor, C.EVT_SCAN_REQUESTED,
            {"run_id": run_id, "started_at": run["started_at"], "pid": os.getpid(), "host": socket.gethostname()},
        )
        return True

    def attach_thread(self, thread: threading.Thread) -> None:
        with self._lock:
            self._thread = thread

    def reset(self) -> None:
        """Back to idle (the demo reset). The audit rows stay: the next
        reconstruction only looks at events after the latest demo_reset."""
        with self._lock:
            self._run = None
            self._loaded = True
            self._foreign = False
            self._thread = None
            self._pacing_ms_total = 0
            try:
                with Session(db_session.get_engine()) as db:
                    self._reset_seen = db.scalar(
                        select(func.max(AuditLog.id)).where(AuditLog.event == C.EVT_DEMO_RESET)
                    ) or 0
            except Exception:
                self._reset_seen = 0

    # ── stage updates (called from the runner thread) ─────────────────────

    def _stage(self, key: str) -> dict[str, Any]:
        for stage in self._run["stages"]:  # type: ignore[index]
            if stage["key"] == key:
                return stage
        raise KeyError(key)

    def stage_status(self, key: str) -> str:
        with self._lock:
            return self._stage(key)["status"]

    def stage_start(self, key: str, detail_en: str = "", detail_ar: str = "") -> None:
        """Start a stage. Any EARLIER stage still pending is closed as done
        with an honest "nothing to do" detail: the graph skips a step it has
        no work for, and the checklist should not show it as forever pending."""
        with self._lock:
            order = list(C.STAGE_KEYS)
            for earlier in order[: order.index(key)]:
                st = self._stage(earlier)
                if st["status"] == "pending":
                    self._close_skipped(st)
            st = self._stage(key)
            if st["status"] != "pending":
                return
            st["status"] = "running"
            st["started_at"] = utc_iso()
            st["detail_en"], st["detail_ar"] = detail_en, detail_ar
            run_id = self._run["run_id"]  # type: ignore[index]
            payload = {
                "run_id": run_id, "stage": key, "label_en": st["label_en"], "label_ar": st["label_ar"],
                "started_at": st["started_at"],
            }
        self._audit(C.ACTOR_RUNNER, C.EVT_STAGE_STARTED, payload)

    def stage_progress(self, key: str, counts: dict[str, Any] | None = None,
                       detail_en: str | None = None, detail_ar: str | None = None) -> None:
        """Live tick inside a running stage. Memory only, not audited."""
        with self._lock:
            st = self._stage(key)
            if st["status"] != "running":
                return
            if counts:
                st["counts"] = {**st["counts"], **counts}
            if detail_en is not None:
                st["detail_en"] = detail_en
            if detail_ar is not None:
                st["detail_ar"] = detail_ar

    def stage_done(self, key: str, counts: dict[str, Any], detail_en: str, detail_ar: str, *, pace: bool = True) -> None:
        with self._lock:
            st = self._stage(key)
            if st["status"] == "pending":  # finished before it was announced
                st["status"] = "running"
                st["started_at"] = utc_iso()
            st["status"] = "done"
            st["ended_at"] = utc_iso()
            st["counts"] = {**st["counts"], **counts}
            st["detail_en"], st["detail_ar"] = detail_en, detail_ar
            payload = {
                "run_id": self._run["run_id"],  # type: ignore[index]
                "stage": key, "status": "done", "counts": st["counts"],
                "detail_en": detail_en, "detail_ar": detail_ar,
                "started_at": st["started_at"], "ended_at": st["ended_at"],
            }
        self._audit(C.ACTOR_RUNNER, C.EVT_STAGE_COMPLETED, payload)
        if pace:
            self._pace()

    def _close_skipped(self, st: dict[str, Any]) -> None:
        now = utc_iso()
        st["status"] = "done"
        st["started_at"] = st["started_at"] or now
        st["ended_at"] = now
        st["detail_en"] = "Nothing to do in this step for this run."
        st["detail_ar"] = "لا يوجد ما يستدعي التنفيذ في هذه الخطوة ضمن هذا التشغيل."
        payload = {
            "run_id": self._run["run_id"],  # type: ignore[index]
            "stage": st["key"], "status": "done", "counts": st["counts"], "skipped": True,
            "detail_en": st["detail_en"], "detail_ar": st["detail_ar"],
            "started_at": st["started_at"], "ended_at": st["ended_at"],
        }
        self._audit(C.ACTOR_RUNNER, C.EVT_STAGE_COMPLETED, payload)

    def _pace(self) -> None:
        ms = max(0, int(settings.demo_stage_pacing_ms)) if settings.demo_mode else 0
        if ms:
            time.sleep(ms / 1000.0)
            with self._lock:
                self._pacing_ms_total += ms

    def set_note(self, note_en: str, note_ar: str) -> None:
        with self._lock:
            if self._run is not None:
                self._run["note_en"], self._run["note_ar"] = note_en, note_ar

    def truncate_stages(self, keep: list[str]) -> None:
        """A run that finds nothing to do lists only the stages it ran."""
        with self._lock:
            self._run["stages"] = [s for s in self._run["stages"] if s["key"] in keep]  # type: ignore[index]

    def finish(self, status: str, summary: dict[str, Any] | None = None) -> None:
        """Terminal state for a run that did not fail: awaiting_review or completed."""
        if status not in ("awaiting_review", "completed"):
            raise ValueError(status)
        with self._lock:
            run = self._run
            if run is None:
                return
            for st in run["stages"]:
                if st["status"] == "pending":
                    self._close_skipped(st)
            run["status"] = status
            run["finished_at"] = utc_iso()
            run["summary"] = summary or {}
            payload = {
                "run_id": run["run_id"], "status": status, "finished_at": run["finished_at"],
                "summary": run["summary"], "stage_keys": [s["key"] for s in run["stages"]],
                "note_en": run["note_en"], "note_ar": run["note_ar"],
            }
        self._audit(C.ACTOR_RUNNER, C.EVT_SCAN_COMPLETED, payload)

    def fail(self, reason: str, error_type: str = "Error") -> None:
        """Terminal failure. The running stage (or, failing that, the first
        unfinished one) is marked failed with the reason. Never a success."""
        with self._lock:
            run = self._run
            if run is None or run["status"] != "running":
                return
            target = next((s for s in run["stages"] if s["status"] == "running"), None) \
                or next((s for s in run["stages"] if s["status"] == "pending"), None)
            stage_key = target["key"] if target else None
            if target is not None:
                target["status"] = "failed"
                target["started_at"] = target["started_at"] or utc_iso()
                target["ended_at"] = utc_iso()
                target["detail_en"] = f"Failed: {reason}"
                target["detail_ar"] = f"تعذر إكمال هذه الخطوة: {reason}"
            run["status"] = "failed"
            run["finished_at"] = utc_iso()
            run["error"] = {"stage": stage_key, "reason": reason, "error_type": error_type}
            payload = {
                "run_id": run["run_id"], "stage": stage_key, "reason": reason, "error_type": error_type,
                "finished_at": run["finished_at"],
            }
        self._audit(C.ACTOR_RUNNER, C.EVT_SCAN_FAILED, payload)

    # ── audit mirror and recovery ─────────────────────────────────────────

    @staticmethod
    def _audit(actor: str, event: str, payload: dict[str, Any]) -> None:
        audit.record_in_new_session(actor=actor, event=event, ref_type="demo_run", payload=payload)

    def ensure_loaded(self) -> None:
        with self._lock:
            if self._loaded:
                return
            self._reload()
            self._loaded = True

    def _sync_reset(self) -> None:
        """A demo_reset written by ANOTHER process (for example
        `python -m app.demo.prepare`) invalidates what this process holds.
        Skipped while a scan thread of this process is alive."""
        if self._thread is not None and self._thread.is_alive():
            return
        with Session(db_session.get_engine()) as db:
            latest = db.scalar(select(func.max(AuditLog.id)).where(AuditLog.event == C.EVT_DEMO_RESET)) or 0
        if latest != self._reset_seen:
            self._reload()

    def _reload(self) -> None:
        """Rebuild the run from audit_log (first use after a restart, or a
        refresh of a run owned by another process)."""
        run, foreign_pid = self._reconstruct()
        self._foreign = False
        if run is not None and run["status"] == "running":
            if foreign_pid is not None and foreign_pid != os.getpid() and pid_alive(foreign_pid):
                self._foreign = True
            else:
                # Nothing is running it: the process ended mid-run.
                run_id = run["run_id"]
                self._run = run
                self.fail(
                    "Interrupted: the process running this scan ended before it finished "
                    "(server restart or crash). Reset the demo and scan again.",
                    error_type="Interrupted",
                )
                return
        self._run = run

    def _reconstruct(self) -> tuple[dict[str, Any] | None, int | None]:
        with Session(db_session.get_engine()) as db:
            last_reset = db.scalar(select(func.max(AuditLog.id)).where(AuditLog.event == C.EVT_DEMO_RESET)) or 0
            self._reset_seen = last_reset
            request = db.scalar(
                select(AuditLog)
                .where(AuditLog.event == C.EVT_SCAN_REQUESTED, AuditLog.id > last_reset)
                .order_by(AuditLog.id.desc())
                .limit(1)
            )
            if request is None:
                return None, None
            run_id = (request.payload_json or {}).get("run_id")
            events = [
                e for e in db.scalars(
                    select(AuditLog)
                    .where(AuditLog.id >= request.id, AuditLog.event.in_(C.RUN_EVENTS))
                    .order_by(AuditLog.id)
                )
                if (e.payload_json or {}).get("run_id") == run_id
            ]
        run = _blank_run(run_id, "running")
        run["started_at"] = (request.payload_json or {}).get("started_at")
        run["thread_id"] = f"demo-{run_id}"
        pid = (request.payload_json or {}).get("pid")
        for event in events:
            p = event.payload_json or {}
            if event.event == C.EVT_STAGE_STARTED:
                st = _find(run, p.get("stage"))
                if st:
                    st["status"], st["started_at"] = "running", p.get("started_at")
            elif event.event == C.EVT_STAGE_COMPLETED:
                st = _find(run, p.get("stage"))
                if st:
                    st.update(
                        status="done", counts=p.get("counts") or {}, detail_en=p.get("detail_en", ""),
                        detail_ar=p.get("detail_ar", ""), started_at=p.get("started_at"), ended_at=p.get("ended_at"),
                    )
            elif event.event == C.EVT_SCAN_COMPLETED:
                run["status"] = p.get("status", "completed")
                run["finished_at"] = p.get("finished_at")
                run["summary"] = p.get("summary") or {}
                run["note_en"] = p.get("note_en", run["note_en"])
                run["note_ar"] = p.get("note_ar", run["note_ar"])
                keys = p.get("stage_keys")
                if keys:
                    run["stages"] = [s for s in run["stages"] if s["key"] in keys]
            elif event.event == C.EVT_SCAN_FAILED:
                run["status"] = "failed"
                run["finished_at"] = p.get("finished_at")
                run["error"] = {"stage": p.get("stage"), "reason": p.get("reason"), "error_type": p.get("error_type")}
                st = _find(run, p.get("stage"))
                if st:
                    st["status"] = "failed"
                    st["detail_en"] = f"Failed: {p.get('reason')}"
                    st["detail_ar"] = f"تعذر إكمال هذه الخطوة: {p.get('reason')}"
        return run, pid


def _find(run: dict[str, Any], key: str | None) -> dict[str, Any] | None:
    return next((s for s in run["stages"] if s["key"] == key), None)


def _copy(run: dict[str, Any]) -> dict[str, Any]:
    import copy

    return copy.deepcopy(run)


TRACKER = RunTracker()
