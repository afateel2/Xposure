"""
Digest tests (new capability: `python -m app.digest`).

Same discipline as test_agent.py/test_routes.py: a real SQLAlchemy session
against an in-memory SQLite database, not a mocked Session — build_digest's
interesting behavior IS its SQL (the watermark read, the priority-band
filter, the "crossed into overdue since last watermark" filter), and a
mock would happily agree with whatever the code did.

The watermark in these tests is planted directly as an AuditLog row
(rather than produced by a real prior `run_digest_cli()` call) so each
scenario can pin exact timestamps/dates without racing the wall clock —
due-date crossing is date-granularity, and a real "digest sent a moment
ago" watermark would land on today's date, which can never satisfy both
"due_date >= watermark_date" and "due_date < today" at once.
"""

from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import digest as digest_mod
from app.db.base import Base
from app.db.models import Action, AuditLog, Change, Regulation, RegulationVersion, Regulator


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture()
def db(engine):
    with Session(engine) as session:
        yield session


def seed_regulation(db: Session) -> list[RegulationVersion]:
    regulator = Regulator(code="nca", name_en="NCA", name_ar="الهيئة", weight=1.0)
    db.add(regulator)
    db.flush()
    regulation = Regulation(regulator_id=regulator.id, code="ecc", title_en="ECC", title_ar="الضوابط")
    db.add(regulation)
    db.flush()
    versions = []
    for label in ("1-2018", "2-2024"):
        version = RegulationVersion(regulation_id=regulation.id, version_label=label, file_sha256=f"hash-{label}")
        db.add(version)
        versions.append(version)
    db.commit()
    return versions


def make_change(db: Session, versions: list[RegulationVersion], **kwargs) -> Change:
    defaults = dict(
        regulation_id=versions[0].regulation_id,
        from_version_id=versions[0].id,
        to_version_id=versions[1].id,
        old_clause_id="2-5-1",
        new_clause_id="2-5-1",
        match_kind="exact_id",
        change_type="new_obligation",
        material=True,
        confidence=0.9,
        summary_en="A new obligation appeared.",
        created_at=datetime.utcnow(),
    )
    defaults.update(kwargs)
    change = Change(**defaults)
    db.add(change)
    db.commit()
    return change


def plant_watermark(db: Session, ts: datetime) -> None:
    db.add(AuditLog(actor="agent:digest", event="digest_sent", ts=ts, payload_json={}))
    db.commit()


# ── build_digest: first run, watermark, newly-overdue ──────────────────────

def test_first_run_reports_new_critical_or_high_change(db):
    versions = seed_regulation(db)
    today = date.today()
    # Already-effective (overdue-ish deadline_factor) new_obligation with no
    # impacted nodes still floors at "medium" per priority.py's guaranteed
    # property; push the deadline in close so it clears into high/critical.
    change = make_change(
        db,
        versions,
        effective_date=today - timedelta(days=2),
        grace_days=None,
        created_at=datetime.utcnow() - timedelta(days=1),
    )

    result = digest_mod.build_digest(db)

    assert result is not None
    assert result["since"] is None
    assert [c["id"] for c in result["new_critical_or_high_changes"]] == [change.id]
    entry = result["new_critical_or_high_changes"][0]
    assert entry["band"] in ("critical", "high")
    assert entry["change_type"] == "new_obligation"
    assert entry["clause_ref"] == "2-5-1"
    assert result["newly_overdue_actions"] == []
    assert "Xposure digest" in result["summary_text"]


def test_second_run_with_nothing_new_returns_none(db):
    versions = seed_regulation(db)
    today = date.today()
    watermark_ts = datetime.utcnow() - timedelta(days=3)

    make_change(
        db,
        versions,
        effective_date=today - timedelta(days=2),
        grace_days=None,
        created_at=watermark_ts - timedelta(days=1),
    )
    plant_watermark(db, watermark_ts)

    assert digest_mod.build_digest(db) is None


def test_second_run_picks_up_only_the_newly_overdue_action(db):
    versions = seed_regulation(db)
    today = date.today()
    watermark_ts = datetime.utcnow() - timedelta(days=3)
    watermark_date = watermark_ts.date()

    # Already-reported change: created before the watermark, and its own
    # due date was already overdue before the watermark too (not "newly"
    # overdue) — must not reappear in either list.
    old_change = make_change(
        db,
        versions,
        old_clause_id="1-1-1",
        new_clause_id="1-1-1",
        effective_date=watermark_date - timedelta(days=5),
        grace_days=None,
        created_at=watermark_ts - timedelta(days=1),
    )
    old_action = Action(
        change_id=old_change.id, type="update_policy", level="draft_then_approve", status="pending"
    )
    db.add(old_action)
    db.commit()

    # New change/action whose due_date crosses into overdue between the
    # watermark and today: watermark_date < due_date < today.
    new_change = make_change(
        db,
        versions,
        old_clause_id="1-1-2",
        new_clause_id="1-1-2",
        change_type="clarification",  # deliberately not critical/high, isolates the action assertion
        effective_date=watermark_date + timedelta(days=1),
        grace_days=None,
        created_at=watermark_ts - timedelta(days=1),
    )
    new_action = Action(
        change_id=new_change.id, type="collect_evidence", level="draft_then_approve", status="pending"
    )
    db.add(new_action)
    db.commit()

    plant_watermark(db, watermark_ts)

    result = digest_mod.build_digest(db)

    assert result is not None
    assert result["new_critical_or_high_changes"] == []
    assert [a["id"] for a in result["newly_overdue_actions"]] == [new_action.id]
    entry = result["newly_overdue_actions"][0]
    assert entry["change_id"] == new_change.id
    assert entry["type"] == "collect_evidence"
    assert entry["due_date"] == (watermark_date + timedelta(days=1)).isoformat()


def test_approved_action_past_due_is_not_reported(db):
    versions = seed_regulation(db)
    today = date.today()
    change = make_change(db, versions, effective_date=today - timedelta(days=2), grace_days=None)
    action = Action(change_id=change.id, type="update_policy", level="draft_then_approve", status="approved")
    db.add(action)
    db.commit()

    result = digest_mod.build_digest(db)

    # change itself may still surface (new_obligation, near deadline); the
    # point of this test is that the approved action must not.
    if result is not None:
        assert result["newly_overdue_actions"] == []


# ── run_digest_cli ───────────────────────────────────────────────────────

def test_run_digest_cli_skips_and_audits_when_nothing_to_report(db, engine, capsys):
    with patch.object(digest_mod, "get_engine", lambda: engine):
        digest_mod.run_digest_cli()

    out = capsys.readouterr().out
    assert "[digest] nothing to report" in out

    rows = list(db.scalars(select(AuditLog).where(AuditLog.event == "digest_skipped")))
    assert len(rows) == 1
    assert rows[0].actor == "agent:digest"
    assert rows[0].payload_json == {"reason": "nothing new since last digest"}


def test_run_digest_cli_sends_notification_and_audits_digest_sent(db, engine):
    versions = seed_regulation(db)
    today = date.today()
    make_change(db, versions, effective_date=today - timedelta(days=2), grace_days=None)

    fake_notify_result = {"sent": True, "channel": "email", "target": "compliance@example.com"}
    fake_webhook_result = {"sent": True, "event": "digest.sent", "status_code": 200}

    with patch.object(digest_mod, "get_engine", lambda: engine), patch.object(
        digest_mod.notify, "send_notification", return_value=fake_notify_result
    ) as mock_notify, patch.object(
        digest_mod.webhooks, "send_webhook", return_value=fake_webhook_result
    ) as mock_webhook:
        digest_mod.run_digest_cli()

    mock_notify.assert_called_once()
    notify_kwargs = mock_notify.call_args.kwargs
    assert notify_kwargs["channel"] is None
    assert notify_kwargs["subject"] == "Xposure digest"
    assert "new_critical_or_high_changes" in notify_kwargs["payload"]

    mock_webhook.assert_called_once()
    assert mock_webhook.call_args.args[0] == "digest.sent"

    rows = list(db.scalars(select(AuditLog).where(AuditLog.event == "digest_sent")))
    assert len(rows) == 1
    assert rows[0].actor == "agent:digest"
    assert rows[0].payload_json["notify_result"] == fake_notify_result
    assert rows[0].payload_json["webhook_result"] == fake_webhook_result
    assert len(rows[0].payload_json["new_critical_or_high_changes"]) == 1
