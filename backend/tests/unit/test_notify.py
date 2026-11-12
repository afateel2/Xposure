"""
Unit tests for app/notify.py — same discipline as test_webhooks.py's
send_webhook tests, since notify.send_notification is deliberately built
to the same honest-degrade contract. smtplib.SMTP is mocked at its single
call site (app.notify.smtplib.SMTP); these tests are about our own
opt-in/degrade logic, not about actually reaching a mail server.
"""

from unittest.mock import MagicMock, patch

import pytest

from app import notify
from app.config import settings


def test_send_notification_rejects_unknown_channel():
    with pytest.raises(ValueError, match="Unknown notification channel"):
        notify.send_notification("carrier_pigeon", "a@b.com", "subject", "message")


def test_send_notification_is_a_noop_when_no_channel_configured(monkeypatch):
    monkeypatch.setattr(settings, "notification_channel", "")
    with patch("app.notify.smtplib.SMTP") as mock_smtp:
        result = notify.send_notification(None, "a@b.com", "subject", "message")
    mock_smtp.assert_not_called()
    assert result == {"sent": False, "reason": "no notification channel configured"}


def test_send_notification_is_a_noop_when_no_recipient_given(monkeypatch):
    monkeypatch.setattr(settings, "notification_channel", "email")
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.test")
    with patch("app.notify.smtplib.SMTP") as mock_smtp:
        result = notify.send_notification(None, None, "subject", "message")
    mock_smtp.assert_not_called()
    assert result == {"sent": False, "channel": "email", "reason": "no recipient contact given"}


def test_send_notification_is_a_noop_when_no_smtp_host_configured(monkeypatch):
    monkeypatch.setattr(settings, "notification_channel", "email")
    monkeypatch.setattr(settings, "smtp_host", "")
    with patch("app.notify.smtplib.SMTP") as mock_smtp:
        result = notify.send_notification(None, "a@b.com", "subject", "message")
    mock_smtp.assert_not_called()
    assert result == {"sent": False, "channel": "email", "target": "a@b.com", "reason": "no SMTP host configured"}


def test_send_notification_sends_when_fully_configured(monkeypatch):
    monkeypatch.setattr(settings, "notification_channel", "email")
    monkeypatch.setattr(settings, "notification_from", "xposure@example.test")
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.test")
    monkeypatch.setattr(settings, "smtp_port", 587)
    monkeypatch.setattr(settings, "smtp_username", "")

    mock_conn = MagicMock()
    mock_smtp_cm = MagicMock()
    mock_smtp_cm.__enter__ = MagicMock(return_value=mock_conn)
    mock_smtp_cm.__exit__ = MagicMock(return_value=False)
    with patch("app.notify.smtplib.SMTP", return_value=mock_smtp_cm) as mock_smtp:
        result = notify.send_notification(None, "a@b.com", "You're assigned", "Please handle this.")

    assert result == {"sent": True, "channel": "email", "target": "a@b.com"}
    mock_smtp.assert_called_once_with("smtp.example.test", 587, timeout=notify._TIMEOUT_SECONDS)
    mock_conn.starttls.assert_called_once()
    mock_conn.login.assert_not_called()  # no smtp_username configured
    mock_conn.send_message.assert_called_once()
    sent_email = mock_conn.send_message.call_args[0][0]
    assert sent_email["To"] == "a@b.com"
    assert sent_email["From"] == "xposure@example.test"
    assert sent_email["Subject"] == "You're assigned"


def test_send_notification_catches_delivery_failure(monkeypatch):
    monkeypatch.setattr(settings, "notification_channel", "email")
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.test")
    with patch("app.notify.smtplib.SMTP", side_effect=OSError("connection refused")):
        result = notify.send_notification(None, "a@b.com", "subject", "message")
    assert result == {
        "sent": False, "channel": "email", "target": "a@b.com", "reason": "OSError: connection refused",
    }


def test_send_notification_explicit_channel_overrides_settings_default(monkeypatch):
    # settings.notification_channel is unset, but an explicit channel arg
    # should still be honored (and still degrade honestly without an SMTP
    # host configured) — this is what routes/actions.py's delegate
    # endpoint relies on being able to pass through explicitly later.
    monkeypatch.setattr(settings, "notification_channel", "")
    monkeypatch.setattr(settings, "smtp_host", "")
    result = notify.send_notification("email", "a@b.com", "subject", "message")
    assert result == {"sent": False, "channel": "email", "target": "a@b.com", "reason": "no SMTP host configured"}
