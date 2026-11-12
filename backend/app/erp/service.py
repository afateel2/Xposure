"""Odoo operations the demo needs: status, employees, create a task in the
"Compliance Actions" project, read a task's live state.

Pure Odoo-side logic (no database session): the Xposure side of a
delegation lives in delegate.py and sync.py. Every function takes an
OdooClient so tests can drive it through a fake transport.
"""

import re
from datetime import datetime, timezone
from typing import Any

from .client import ErpError, OdooClient
from .settings import ErpSettings, get_erp_settings

STAGE_KEYS = ("new", "in_progress", "waiting", "done")

# Stage name (lower case, normalised) -> stage_key. Names come from
# scripts/odoo_seed.py; a stage a person added by hand maps to "other".
_STAGE_NAME_TO_KEY = {
    "new": "new",
    "in progress": "in_progress",
    "waiting for confirmation": "waiting",
    "done": "done",
}

# project.task.state values that mean "closed as done". The green check on
# a Kanban card sets state 1_done without moving the card, so both signals
# count as done.
_DONE_STATES = {"1_done"}

_TASK_FIELDS = ["name", "stage_id", "user_ids", "project_id", "date_deadline", "state", "write_date"]


def stage_key_for(stage_name: str | None, state: str | None = None) -> str:
    if state in _DONE_STATES:
        return "done"
    normalised = re.sub(r"\s+", " ", (stage_name or "").strip().lower())
    return _STAGE_NAME_TO_KEY.get(normalised, "other")


def _m2o_name(value: Any) -> str | None:
    """Many2one comes back as [id, display_name] (or false)."""
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return str(value[1])
    return None


def _m2o_id(value: Any) -> int | None:
    if isinstance(value, (list, tuple)) and value:
        return int(value[0])
    return None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class OdooService:
    def __init__(self, client: OdooClient, settings: ErpSettings):
        self.client = client
        self.settings = settings

    # -- helpers -----------------------------------------------------------
    def task_url(self, task_id: int) -> str:
        # Odoo 17 form deep link. (Odoo 18 moved to /odoo/action-.../<id>;
        # /web#... is the form this image serves.)
        return f"{self.settings.public_url}/web#id={task_id}&model=project.task&view_type=form"

    def project_id(self) -> int:
        name = self.settings.odoo_project_name
        rows = self.client.search_read("project.project", [["name", "=", name]], ["name"], limit=1)
        if not rows:
            raise ErpError(
                "api",
                f"The Odoo project {name!r} does not exist. Run backend/scripts/odoo_seed.py to create it.",
                f"مشروع Odoo باسم {name!r} غير موجود. شغّل backend/scripts/odoo_seed.py لإنشائه.",
            )
        return int(rows[0]["id"])

    def _first_stage_id(self, project_id: int) -> int | None:
        stages = self.client.search_read(
            "project.task.type",
            [["project_ids", "in", [project_id]]],
            ["name", "sequence"],
            order="sequence, id",
        )
        if not stages:
            return None
        for stage in stages:
            if stage_key_for(stage.get("name")) == "new":
                return int(stage["id"])
        return int(stages[0]["id"])

    # -- status / employees ------------------------------------------------
    def employees(self) -> list[dict[str, Any]]:
        # The integration account's own employee record (the Odoo admin) is
        # not a person to delegate to, so it is left out of the picker.
        integration_uid = self.client.authenticate()
        rows = self.client.search_read(
            "hr.employee",
            [["active", "=", True], ["user_id", "!=", integration_uid]],
            ["name", "job_title", "work_email", "department_id", "user_id"],
            order="id",
        )
        return [
            {
                "id": int(r["id"]),
                "name": r.get("name") or "",
                "job_title": r.get("job_title") or None,
                "work_email": r.get("work_email") or None,
                "department": _m2o_name(r.get("department_id")),
            }
            for r in rows
        ]

    def employee(self, employee_id: int) -> dict[str, Any]:
        rows = self.client.read(
            "hr.employee", [employee_id], ["name", "job_title", "work_email", "department_id", "user_id"]
        )
        if not rows:
            raise ErpError(
                "not_found",
                f"No employee with id {employee_id} exists in Odoo.",
                f"لا يوجد موظف بالمعرف {employee_id} في نظام Odoo.",
            )
        r = rows[0]
        return {
            "id": int(r["id"]),
            "name": r.get("name") or "",
            "job_title": r.get("job_title") or None,
            "work_email": r.get("work_email") or None,
            "department": _m2o_name(r.get("department_id")),
            "user_id": _m2o_id(r.get("user_id")),
        }

    # -- tasks -------------------------------------------------------------
    def create_task(
        self,
        *,
        name: str,
        description_html: str,
        employee: dict[str, Any],
        due_date: str | None,
        important: bool,
    ) -> dict[str, Any]:
        project_id = self.project_id()
        values: dict[str, Any] = {
            "name": name,
            "project_id": project_id,
            "description": description_html,
            # "1" is Odoo's starred/important priority, "0" normal.
            "priority": "1" if important else "0",
        }
        stage_id = self._first_stage_id(project_id)
        if stage_id is not None:
            values["stage_id"] = stage_id
        if employee.get("user_id"):
            values["user_ids"] = [[6, 0, [int(employee["user_id"])]]]
        if due_date:
            values["date_deadline"] = due_date
        task_id = self.client.create("project.task", values)
        state = self.task_state(task_id)
        state["assignee"] = state.get("assignee") or employee.get("name")
        return state

    def task_state(self, task_id: int) -> dict[str, Any]:
        rows = self.client.read("project.task", [task_id], _TASK_FIELDS)
        if not rows:
            raise ErpError(
                "not_found",
                f"The Odoo task {task_id} no longer exists (deleted in Odoo).",
                f"مهمة Odoo رقم {task_id} لم تعد موجودة (حُذفت في Odoo).",
            )
        r = rows[0]
        stage = _m2o_name(r.get("stage_id"))
        state = r.get("state") or None
        assignee = self._assignee_names(r.get("user_ids") or [])
        return {
            "task_id": int(r["id"]),
            "url": self.task_url(int(r["id"])),
            "name": r.get("name"),
            "stage": stage,
            "stage_key": stage_key_for(stage, state),
            "odoo_state": state,
            "assignee": assignee,
            "date_deadline": r.get("date_deadline") or None,
            "synced_at": now_iso(),
        }

    def delete_task(self, task_id: int) -> bool:
        """Delete one task Xposure created. True when it was deleted, False
        when nothing was deleted because the task no longer exists in Odoo or
        does not belong to the configured Xposure project (an id that Odoo
        reused for something else is never touched). Raises ErpError on
        connectivity, auth or API problems."""
        project_id = self.project_id()
        rows = self.client.search_read(
            "project.task",
            [["id", "=", int(task_id)], ["project_id", "=", project_id]],
            ["id"],
            limit=1,
            context={"active_test": False},  # archived tasks count too
        )
        if not rows:
            return False
        self.client.execute_kw("project.task", "unlink", [[int(task_id)]])
        return True

    def _assignee_names(self, user_ids: list[int]) -> str | None:
        if not user_ids:
            return None
        users = self.client.read("res.users", [int(u) for u in user_ids], ["name"])
        names = [str(u.get("name")) for u in users if u.get("name")]
        return ", ".join(names) or None


def build_service() -> OdooService:
    """A service for the configured Odoo, or ErpError(not_configured)."""
    settings = get_erp_settings()
    client = OdooClient(settings)  # raises not_configured when unset
    return OdooService(client, settings)


def status() -> dict[str, Any]:
    """Never raises: this is the honest 'what is the ERP situation' answer."""
    settings = get_erp_settings()
    base: dict[str, Any] = {
        "configured": settings.configured,
        "reachable": False,
        "authenticated": False,
        "project_found": False,
        "system": "odoo",
        "version": None,
        "database": settings.odoo_db or None,
        "url": settings.public_url or None,
    }
    if not settings.configured:
        base["message_en"] = (
            "The ERP (Odoo) is not configured. Set ODOO_URL and ODOO_PASSWORD in .env, then start it with "
            "docker compose --profile odoo up -d."
        )
        base["message_ar"] = (
            "نظام Odoo غير مهيأ. حدد ODOO_URL وODOO_PASSWORD في ملف .env ثم شغّله عبر "
            "docker compose --profile odoo up -d."
        )
        return base

    try:
        client = OdooClient(settings)
    except ErpError as exc:  # pragma: no cover - configured was checked above
        base["message_en"], base["message_ar"] = exc.message_en, exc.message_ar
        return base
    with client:
        try:
            info = client.version()
        except ErpError as exc:
            base["message_en"], base["message_ar"] = exc.message_en, exc.message_ar
            return base
        base["reachable"] = True
        base["version"] = info.get("server_version") or None
        try:
            client.authenticate()
        except ErpError as exc:
            base["message_en"], base["message_ar"] = exc.message_en, exc.message_ar
            return base
        base["authenticated"] = True
        try:
            OdooService(client, settings).project_id()
            base["project_found"] = True
        except ErpError as exc:
            base["message_en"], base["message_ar"] = exc.message_en, exc.message_ar
            return base

    version = base["version"] or "unknown version"
    base["message_en"] = (
        f"Connected to Odoo {version}, database {settings.odoo_db}, project {settings.odoo_project_name!r}."
    )
    base["message_ar"] = (
        f"تم الاتصال بنظام Odoo (الإصدار {version}) وقاعدة البيانات {settings.odoo_db} "
        f"ومشروع {settings.odoo_project_name!r}."
    )
    return base
