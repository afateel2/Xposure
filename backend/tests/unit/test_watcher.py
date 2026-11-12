"""
app/watcher.py and the /sources/check-live routes: a real, on-demand check
against a regulator's own public page (see that module's docstring for
scope and what it deliberately does not do).

One real network call against the live nca.gov.sa page was made by hand
while building this (not repeated here on every test run): it correctly
found "ECC 2-2024" and the real cdn.nca.gov.sa PDF link, and correctly
reported new_version_available against a database holding only 1-2018 (the
demo's baseline state at the time). Everything below is a mocked httpx
transport, the same pattern tests/unit/test_erp.py already uses for a fake
Odoo, so the branch coverage (matches, conflict, every failure kind) does
not depend on the real site's current state or availability.
"""

import hashlib

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import watcher
from app.auth import require_user
from app.db.base import Base
from app.db.models import AuditLog, Regulation, RegulationVersion, Regulator
from app.db.session import get_db
from app.main import app

from .auth_fixtures import TEST_USER

REAL_PAGE_HTML_FRAGMENT = (
    '<p><a href="https://cdn.nca.gov.sa/api/files/public/upload/'
    '86e09090-44e4-481f-bc28-355673607654_ECC--2024-EN.pdf">Essential '
    'Cybersecurity Controls (ECC 2-2024)</a></p>'
    '<p><a href="https://cdn.nca.gov.sa/api/files/public/upload/'
    '94c6c5f5-4d70-4afd-a440-64369aa667e2_Guide-to-Essential-Cybersecurity-'
    'Controls-(ECC)-Implementation-en.pdf">Implementation Guide</a></p>'
)
PDF_BYTES = b"%PDF-1.4 fake but deterministic content for hashing\n"
PDF_SHA256 = hashlib.sha256(PDF_BYTES).hexdigest()


def _make_target():
    return watcher.WatchTarget(
        regulator_code="nca", regulation_code="ecc",
        page_url="https://nca.gov.sa/en/regulatory-documents/controls-list/ecc",
        version_re=watcher.NCA_ECC_TARGET.version_re,
        pdf_link_re=watcher.NCA_ECC_TARGET.pdf_link_re,
        exclude_name_substrings=("guide", "implementation"),
    )


_RealClient = httpx.Client


def _mock_client(handler):
    def factory(*args, **kwargs):
        kwargs.pop("transport", None)
        return _RealClient(transport=httpx.MockTransport(handler), **kwargs)
    return factory


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _seed(db, version_label="1-2018", sha="aaa"):
    regulator = Regulator(code="nca", name_en="NCA", name_ar="الهيئة")
    db.add(regulator)
    db.flush()
    regulation = Regulation(regulator_id=regulator.id, code="ecc", title_en="ECC", title_ar="الضوابط")
    db.add(regulation)
    db.flush()
    db.add(RegulationVersion(regulation_id=regulation.id, version_label=version_label, file_sha256=sha, source_url=""))
    db.commit()


# ── check_live() direct ─────────────────────────────────────────────────

def test_new_version_available_when_live_label_is_not_ingested(db, monkeypatch):
    _seed(db, "1-2018", "aaa")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=REAL_PAGE_HTML_FRAGMENT)

    monkeypatch.setattr(httpx, "Client", _mock_client(handler))
    result = watcher.check_live(db, _make_target())
    assert result["status"] == "new_version_available"
    assert result["live_version_label"] == "2-2024"
    assert result["pdf_url"].endswith("_ECC--2024-EN.pdf")
    assert "guide" not in result["pdf_url"].lower()
    assert result["file_sha256"] is None


def test_matches_known_when_hash_agrees(db, monkeypatch):
    _seed(db, "2-2024", PDF_SHA256)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".pdf"):
            return httpx.Response(200, content=PDF_BYTES)
        return httpx.Response(200, text=REAL_PAGE_HTML_FRAGMENT)

    monkeypatch.setattr(httpx, "Client", _mock_client(handler))
    result = watcher.check_live(db, _make_target())
    assert result["status"] == "matches_known"
    assert result["file_sha256"] == PDF_SHA256


def test_content_conflict_when_hash_disagrees(db, monkeypatch):
    _seed(db, "2-2024", "not-the-real-hash")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".pdf"):
            return httpx.Response(200, content=PDF_BYTES)
        return httpx.Response(200, text=REAL_PAGE_HTML_FRAGMENT)

    monkeypatch.setattr(httpx, "Client", _mock_client(handler))
    result = watcher.check_live(db, _make_target())
    assert result["status"] == "content_conflict"


def test_never_mistakes_the_implementation_guide_for_the_main_document(db, monkeypatch):
    """Both PDF links are real candidates by URL pattern; only the one
    whose filename does not say "Guide"/"Implementation" may win."""
    _seed(db, "1-2018", "aaa")
    guide_first_html = (
        '<a href="https://cdn.nca.gov.sa/api/files/public/upload/'
        'xxx_Guide-to-Essential-Cybersecurity-Controls-(ECC)-Implementation-en.pdf">Guide</a>'
        '<a href="https://cdn.nca.gov.sa/api/files/public/upload/'
        'yyy_ECC--2024-EN.pdf">ECC 2-2024</a>'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=guide_first_html)

    monkeypatch.setattr(httpx, "Client", _mock_client(handler))
    result = watcher.check_live(db, _make_target())
    assert result["pdf_url"].endswith("_ECC--2024-EN.pdf")


def test_timeout_raises_watcher_error_with_bilingual_message(db, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("simulated timeout", request=request)

    monkeypatch.setattr(httpx, "Client", _mock_client(handler))
    with pytest.raises(watcher.WatcherError) as exc_info:
        watcher.check_live(db, _make_target())
    assert exc_info.value.kind == "timeout"
    assert "|" in exc_info.value.combined


def test_unreachable_site_raises_watcher_error(db, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated DNS failure", request=request)

    monkeypatch.setattr(httpx, "Client", _mock_client(handler))
    with pytest.raises(watcher.WatcherError) as exc_info:
        watcher.check_live(db, _make_target())
    assert exc_info.value.kind == "unreachable"


def test_non_200_page_status_raises_watcher_error(db, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    monkeypatch.setattr(httpx, "Client", _mock_client(handler))
    with pytest.raises(watcher.WatcherError) as exc_info:
        watcher.check_live(db, _make_target())
    assert exc_info.value.kind == "bad_status"


def test_unrecognized_page_layout_raises_watcher_error_not_a_fake_result(db, monkeypatch):
    """The site's real structure changing must never be silently read as
    "no update" — see app/watcher.py's module docstring."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><body>Completely different page</body></html>")

    monkeypatch.setattr(httpx, "Client", _mock_client(handler))
    with pytest.raises(watcher.WatcherError) as exc_info:
        watcher.check_live(db, _make_target())
    assert exc_info.value.kind == "unrecognized_page"


def test_pdf_download_failure_after_finding_a_known_version_raises(db, monkeypatch):
    _seed(db, "2-2024", "aaa")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".pdf"):
            return httpx.Response(500)
        return httpx.Response(200, text=REAL_PAGE_HTML_FRAGMENT)

    monkeypatch.setattr(httpx, "Client", _mock_client(handler))
    with pytest.raises(watcher.WatcherError) as exc_info:
        watcher.check_live(db, _make_target())
    assert exc_info.value.kind == "pdf_unreachable"


# ── Routes ───────────────────────────────────────────────────────────────

@pytest.fixture
def client(db):
    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[require_user] = lambda: TEST_USER
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(require_user, None)
        watcher_cache_clear()


def watcher_cache_clear():
    from app.routes import sources as sources_routes

    sources_routes._last_results.clear()


def test_check_live_route_requires_login(db):
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def _override():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_db] = _override
    try:
        c = TestClient(app)
        resp = c.post("/sources/check-live", params={"regulator": "nca", "regulation": "ecc"})
        assert resp.status_code == 401
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_check_live_route_404s_for_an_unconfigured_target(client):
    resp = client.post("/sources/check-live", params={"regulator": "saso", "regulation": "rohs"})
    assert resp.status_code == 404


def test_check_live_route_writes_an_audit_row_with_the_real_actor(client, db, monkeypatch):
    _seed(db, "1-2018", "aaa")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=REAL_PAGE_HTML_FRAGMENT)

    monkeypatch.setattr(httpx, "Client", _mock_client(handler))
    resp = client.post("/sources/check-live", params={"regulator": "nca", "regulation": "ecc"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "new_version_available"
    assert body["from_cache"] is False

    row = db.scalar(select(AuditLog).where(AuditLog.event == "live_portal_checked"))
    assert row is not None
    assert row.actor == TEST_USER.actor()
    assert row.payload_json["live_version_label"] == "2-2024"


def test_check_live_route_is_cached_on_a_second_call(client, db, monkeypatch):
    _seed(db, "1-2018", "aaa")
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, text=REAL_PAGE_HTML_FRAGMENT)

    monkeypatch.setattr(httpx, "Client", _mock_client(handler))
    first = client.post("/sources/check-live", params={"regulator": "nca", "regulation": "ecc"})
    second = client.post("/sources/check-live", params={"regulator": "nca", "regulation": "ecc"})
    assert first.json()["from_cache"] is False
    assert second.json()["from_cache"] is True
    assert calls["n"] == 1  # the real site was only actually hit once


def test_check_live_route_surfaces_a_failure_as_an_http_error_and_audits_it(client, db, monkeypatch):
    _seed(db, "1-2018", "aaa")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("simulated timeout", request=request)

    monkeypatch.setattr(httpx, "Client", _mock_client(handler))
    resp = client.post("/sources/check-live", params={"regulator": "nca", "regulation": "ecc"})
    assert resp.status_code == 504
    assert "|" in resp.json()["detail"]

    row = db.scalar(select(AuditLog).where(AuditLog.event == "live_portal_check_failed"))
    assert row is not None


def test_last_live_check_never_triggers_a_network_call(client, db, monkeypatch):
    called = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        called["n"] += 1
        return httpx.Response(200, text=REAL_PAGE_HTML_FRAGMENT)

    monkeypatch.setattr(httpx, "Client", _mock_client(handler))
    resp = client.get("/sources/check-live/last", params={"regulator": "nca", "regulation": "ecc"})
    assert resp.status_code == 200
    assert resp.json() == {"checked": False}
    assert called["n"] == 0
