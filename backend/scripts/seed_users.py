"""Seed the six named reviewers (idempotent). Run from backend/:

    ./.venv/Scripts/python.exe scripts/seed_users.py

Same six people already seeded into Odoo by scripts/odoo_seed.py, same
emails, so logging into Xposure as one of them and delegating an action to
"IT Security Lead" in Odoo is recognizably the same person end to end.

Password: every seeded user gets the SAME password this run generates (or
reuses, see below) — a pragmatic choice for a single-organization demo
tool with no self-service signup, documented here rather than left
implicit. A real multi-reviewer deployment would want per-user passwords
or SSO (docs/DESIGN.md's Roadmap: out of scope, noted not hidden). The
password is written to .env as DEMO_USER_PASSWORD (generated once, like
ODOO_PASSWORD already is) and never printed to the console.

Roles: Compliance Officer is the one "admin" (may edit the automation
policy, see app/routes/settings.py); everyone else is a "reviewer" (can
approve/dismiss/delegate/undo, exactly as every actor could before auth
existed).
"""

import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.auth import hash_password  # noqa: E402
from app.db.models import AppUser  # noqa: E402
from app.db.session import get_engine  # noqa: E402

ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"

USERS = [
    {"email": "it.security@eastern-industrial.example", "name_en": "Khalid Al-Harbi", "name_ar": "خالد الحربي",
     "job_title_en": "IT Security Lead", "job_title_ar": "رئيس أمن تقنية المعلومات", "role": "reviewer"},
    {"email": "ot.engineering@eastern-industrial.example", "name_en": "Faisal Al-Qahtani", "name_ar": "فيصل القحطاني",
     "job_title_en": "OT Engineering Lead", "job_title_ar": "رئيس هندسة أنظمة التحكم الصناعي", "role": "reviewer"},
    {"email": "operations@eastern-industrial.example", "name_en": "Nasser Al-Dossari", "name_ar": "ناصر الدوسري",
     "job_title_en": "Operations Manager", "job_title_ar": "مدير العمليات", "role": "reviewer"},
    {"email": "compliance@eastern-industrial.example", "name_en": "Reem Al-Mutairi", "name_ar": "ريم المطيري",
     "job_title_en": "Compliance Officer", "job_title_ar": "مسؤولة الامتثال", "role": "admin"},
    {"email": "legal@eastern-industrial.example", "name_en": "Abdullah Al-Otaibi", "name_ar": "عبدالله العتيبي",
     "job_title_en": "Legal Counsel", "job_title_ar": "المستشار القانوني", "role": "reviewer"},
    {"email": "procurement@eastern-industrial.example", "name_en": "Huda Al-Zahrani", "name_ar": "هدى الزهراني",
     "job_title_en": "Procurement Lead", "job_title_ar": "رئيسة المشتريات", "role": "reviewer"},
]


def _get_or_create_password() -> str:
    """Reuse DEMO_USER_PASSWORD from .env if already set (so re-running
    this script does not invalidate a password someone is using), else
    generate one and append it."""
    if ENV_PATH.is_file():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            if line.startswith("DEMO_USER_PASSWORD="):
                value = line.split("=", 1)[1].strip()
                if value:
                    return value
    password = secrets.token_urlsafe(12)
    with ENV_PATH.open("a", encoding="utf-8") as fh:
        fh.write(f"\nDEMO_USER_PASSWORD={password}\n")
    return password


def main() -> None:
    password = _get_or_create_password()
    engine = get_engine()
    created, updated = 0, 0
    with Session(engine) as db:
        for spec in USERS:
            existing = db.scalar(select(AppUser).where(AppUser.email == spec["email"]))
            if existing is None:
                db.add(AppUser(password_hash=hash_password(password), **spec))
                created += 1
            else:
                existing.name_en = spec["name_en"]
                existing.name_ar = spec["name_ar"]
                existing.job_title_en = spec["job_title_en"]
                existing.job_title_ar = spec["job_title_ar"]
                existing.role = spec["role"]
                existing.is_active = True
                updated += 1
        db.commit()
    print(f"Seeded {len(USERS)} user(s): {created} created, {updated} updated.")
    print("Password is in .env as DEMO_USER_PASSWORD (not printed here).")


if __name__ == "__main__":
    main()
