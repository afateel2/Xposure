"""Shared test identity for every route test file that exercises a
mutating endpoint. app/auth.py's require_user/require_admin dependencies
are overridden to this fixed user (role="admin" so admin-gated endpoints,
e.g. PUT /settings/policy, are reachable from existing tests without a
second fixture) rather than requiring every test to actually log in —
the same "override the dependency, not the real thing" pattern this
project already uses for get_db (see test_routes.py's module docstring).
Overriding require_user alone also covers require_admin: FastAPI's
dependency_overrides substitutes a callable everywhere it appears in the
dependency graph, including as another dependency's own sub-dependency.

Dedicated auth-flow tests (test_auth.py) do NOT use this override — they
exercise the real login/logout/session path end to end."""

from app.db.models import AppUser

TEST_USER = AppUser(
    id=1,
    email="test.reviewer@example.com",
    name_en="Test Reviewer",
    name_ar="مراجع الاختبار",
    job_title_en="Reviewer",
    job_title_ar="مراجع",
    role="admin",
    password_hash="not-a-real-hash",
    is_active=True,
)
