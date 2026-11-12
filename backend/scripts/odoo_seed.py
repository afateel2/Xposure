"""Seed the demo Odoo (idempotent), over Odoo's own JSON-RPC.

Run from backend/ after the Odoo database exists:

    ./.venv/Scripts/python.exe scripts/odoo_seed.py

Prerequisite (once, official image, inside the container):

    docker compose --profile odoo up -d odoo-db
    docker compose --profile odoo run --rm odoo odoo -d xposure_erp \
        -i project,hr --without-demo=all --load-language=ar_001 --stop-after-init
    docker compose --profile odoo up -d odoo

What it does (safe to run repeatedly, it only creates what is missing):
  1. Waits for Odoo, logs in as ODOO_USER. A freshly initialised database has
     the well known default admin password; if the configured ODOO_PASSWORD is
     rejected but the default works, the admin password is changed to
     ODOO_PASSWORD (from .env), so no default credential is left behind.
  2. Makes sure English and Arabic are installed.
  3. Creates 6 employees (each with an Odoo user, a work email and a job
     title) for the generic demo company.
  4. Creates the project "Compliance Actions" with the stages New, In
     Progress, Waiting for Confirmation, Done, and no other stages.

Secrets are read from .env and never printed.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app.erp.client import ErpError, OdooClient  # noqa: E402
from app.erp.settings import PROJECT_NAME, get_erp_settings  # noqa: E402

DEFAULT_ADMIN_PASSWORD = "admin"  # what `odoo -i` sets on a brand new database

# The four owner emails match backend/data/org/demo_org.yaml so the delegate
# picker can preselect the employee that owns an impacted node.
EMPLOYEES = [
    {"name": "Khalid Al-Harbi", "job_title": "IT Security Lead", "department": "Information Technology",
     "email": "it.security@eastern-industrial.example"},
    {"name": "Faisal Al-Qahtani", "job_title": "OT Engineering Lead", "department": "Manufacturing Engineering",
     "email": "ot.engineering@eastern-industrial.example"},
    {"name": "Nasser Al-Dossari", "job_title": "Operations Manager", "department": "Operations",
     "email": "operations@eastern-industrial.example"},
    {"name": "Reem Al-Mutairi", "job_title": "Compliance Officer", "department": "Governance and Compliance",
     "email": "compliance@eastern-industrial.example"},
    {"name": "Abdullah Al-Otaibi", "job_title": "Legal Counsel", "department": "Legal",
     "email": "legal@eastern-industrial.example"},
    {"name": "Huda Al-Zahrani", "job_title": "Procurement Lead", "department": "Procurement",
     "email": "procurement@eastern-industrial.example"},
]

STAGES = ["New", "In Progress", "Waiting for Confirmation", "Done"]
LANGS = ["en_US", "ar_001"]


def say(message: str) -> None:
    print(message, flush=True)


def wait_for_odoo(client: OdooClient, timeout_s: int = 180) -> str:
    deadline = time.time() + timeout_s
    last = ""
    while time.time() < deadline:
        try:
            return str(client.version().get("server_version"))
        except ErpError as exc:
            last = exc.message_en
            time.sleep(3)
    raise SystemExit(f"Odoo did not come up within {timeout_s}s: {last}")


def login(settings) -> OdooClient:
    client = OdooClient(settings)
    wait_for_odoo(client)
    try:
        client.authenticate()
        return client
    except ErpError as exc:
        if exc.kind != "auth":
            raise
    # Configured password rejected: a brand new database still has the default.
    default_settings = settings.model_copy(update={"odoo_password": type(settings.odoo_password)(DEFAULT_ADMIN_PASSWORD)})
    bootstrap = OdooClient(default_settings)
    try:
        uid = bootstrap.authenticate()
    except ErpError as exc:
        raise SystemExit(
            "Cannot log in to Odoo with ODOO_PASSWORD, and the default admin password is not valid either. "
            "Is ODOO_PASSWORD in .env the password of this database's admin user?"
        ) from exc
    bootstrap.write("res.users", [uid], {"password": settings.odoo_password.get_secret_value()})
    say("Admin password was the default; changed it to ODOO_PASSWORD from .env.")
    bootstrap.close()
    client.close()
    client = OdooClient(settings)
    client.authenticate()
    return client


def ensure_languages(client: OdooClient) -> None:
    for code in LANGS:
        rows = client.search_read("res.lang", [["code", "=", code]], ["active"], context={"active_test": False})
        if rows and rows[0]["active"]:
            say(f"Language {code}: installed")
            continue
        wizard = client.create("base.language.install", {"overwrite": False, "lang_ids": [[6, 0, [rows[0]["id"]]]]} if rows else {})
        client.execute_kw("base.language.install", "lang_install", [[wizard]])
        say(f"Language {code}: installed now")


def group_ids(client: OdooClient) -> list[int]:
    ids = []
    for module, name in (("base", "group_user"), ("project", "group_project_user")):
        rows = client.search_read("ir.model.data", [["module", "=", module], ["name", "=", name]], ["res_id"], limit=1)
        if rows:
            ids.append(int(rows[0]["res_id"]))
    return ids


def ensure_department(client: OdooClient, name: str) -> int:
    rows = client.search_read("hr.department", [["name", "=", name]], ["name"], limit=1)
    return int(rows[0]["id"]) if rows else client.create("hr.department", {"name": name})


def ensure_employee(client: OdooClient, spec: dict, groups: list[int]) -> str:
    department_id = ensure_department(client, spec["department"])
    users = client.search_read("res.users", [["login", "=", spec["email"]]], ["name"], limit=1)
    if users:
        user_id, user_note = int(users[0]["id"]), "user exists"
    else:
        user_id = client.execute_kw(
            "res.users",
            "create",
            [{"name": spec["name"], "login": spec["email"], "email": spec["email"], "groups_id": [[6, 0, groups]]}],
            {"context": {"no_reset_password": True}},
        )
        user_id, user_note = int(user_id), "user created"

    values = {
        "name": spec["name"],
        "job_title": spec["job_title"],
        "work_email": spec["email"],
        "department_id": department_id,
        "user_id": user_id,
    }
    rows = client.search_read("hr.employee", [["user_id", "=", user_id]], ["name"], limit=1, context={"active_test": False})
    if not rows:
        rows = client.search_read("hr.employee", [["work_email", "=", spec["email"]]], ["name"], limit=1)
    if rows:
        client.write("hr.employee", [int(rows[0]["id"])], values)
        return f"{spec['name']}: employee updated, {user_note}"
    client.create("hr.employee", values)
    return f"{spec['name']}: employee created, {user_note}"


def ensure_project(client: OdooClient) -> None:
    rows = client.search_read("project.project", [["name", "=", PROJECT_NAME]], ["name"], limit=1, context={"active_test": False})
    if rows:
        project_id = int(rows[0]["id"])
        say(f"Project {PROJECT_NAME!r}: exists (id {project_id})")
    else:
        project_id = client.create("project.project", {"name": PROJECT_NAME, "privacy_visibility": "employees"})
        say(f"Project {PROJECT_NAME!r}: created (id {project_id})")

    fields = client.execute_kw("project.task.type", "fields_get", [], {"attributes": ["type"]})
    wanted: dict[str, int] = {}
    for sequence, name in enumerate(STAGES, start=1):
        found = client.search_read("project.task.type", [["name", "=", name], ["project_ids", "in", [project_id]]], ["name"], limit=1)
        values: dict = {"name": name, "sequence": sequence, "fold": False}
        if "is_closed" in fields:
            values["is_closed"] = name == "Done"
        if found:
            stage_id = int(found[0]["id"])
            client.write("project.task.type", [stage_id], values)
        else:
            stage_id = client.create("project.task.type", {**values, "project_ids": [[4, project_id]]})
            say(f"  stage created: {name}")
        wanted[name] = stage_id

    # Unlink any other stage (Odoo's defaults) from this project so the board
    # shows exactly the four stages.
    others = client.search_read(
        "project.task.type",
        [["project_ids", "in", [project_id]], ["id", "not in", list(wanted.values())]],
        ["name"],
    )
    for stage in others:
        client.write("project.task.type", [int(stage["id"])], {"project_ids": [[3, project_id]]})
        say(f"  stage unlinked from project: {stage['name']}")
    say("Project stages: " + ", ".join(STAGES))


def main() -> None:
    settings = get_erp_settings()
    if not settings.configured:
        raise SystemExit("ODOO_URL and ODOO_PASSWORD are not set in .env: nothing to seed.")
    say(f"Seeding Odoo at {settings.odoo_url} (database {settings.odoo_db}, user {settings.odoo_user})")
    try:
        client = login(settings)
    except (ErpError, httpx.HTTPError) as exc:
        raise SystemExit(f"Cannot reach or log in to Odoo: {exc}") from exc
    with client:
        ensure_languages(client)
        groups = group_ids(client)
        for spec in EMPLOYEES:
            say(ensure_employee(client, spec, groups))
        ensure_project(client)
    say("Done.")


if __name__ == "__main__":
    main()
