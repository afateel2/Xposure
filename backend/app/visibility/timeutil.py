"""
Time helpers. The database stores naive UTC datetimes (datetime.utcnow on
audit_log/change/action, datetime.now(timezone.utc) stripped by the driver on
delegated_at/confirmed_at). On the wire the visibility endpoints always emit
timezone-aware UTC ("...Z"), so a browser never mistakes a naive timestamp for
local time.
"""

from datetime import datetime, timezone


def as_utc(value: datetime | None) -> datetime | None:
    """Naive datetimes are taken to be UTC (that is what the DB holds)."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def to_naive_utc(value: datetime) -> datetime:
    """For comparing against DB columns."""
    return as_utc(value).replace(tzinfo=None)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso(value: str) -> datetime:
    """Parse an ISO-8601 timestamp (with 'Z', an offset, or naive = UTC).
    Raises ValueError on garbage; callers turn that into a 422."""
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    # A query string turns '+' into a space; put it back for "...T10:00:00 00:00".
    if " " in text and "T" in text.split(" ")[0]:
        head, _, tail = text.partition(" ")
        if len(tail) == 5 and tail[2] == ":":
            text = f"{head}+{tail}"
    return as_utc(datetime.fromisoformat(text))
