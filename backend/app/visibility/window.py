"""
The "since the last demo reset" window.

The demo reset appends a `demo_reset` audit event (audit_log itself is never
truncated). For scan and change timestamps the meaningful history therefore
starts at the newest such event, not at the beginning of time. Rows are
compared by audit id (monotonic) rather than by timestamp so a clock jump can
never move an event across the boundary.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import AuditLog

RESET_EVENT = "demo_reset"


@dataclass(frozen=True)
class Window:
    """active=True means the reset boundary applies (since_reset requested AND
    a demo_reset event exists). reset_id/reset_at describe the newest reset
    whenever one exists, even when the filter is off, so responses can always
    say when the demo was last reset."""

    active: bool
    reset_id: int | None
    reset_at: datetime | None  # naive UTC, as stored

    def ts_ok(self, ts: datetime | None) -> bool:
        """True if a naive-UTC timestamp falls inside the window."""
        if ts is None:
            return False
        if not self.active or self.reset_at is None:
            return True
        return ts >= self.reset_at

    def id_ok(self, audit_id: int) -> bool:
        if not self.active or self.reset_id is None:
            return True
        return audit_id >= self.reset_id


def get_window(db: Session, since_reset: bool = True) -> Window:
    row = db.scalar(select(AuditLog).where(AuditLog.event == RESET_EVENT).order_by(AuditLog.id.desc()).limit(1))
    if row is None:
        return Window(active=False, reset_id=None, reset_at=None)
    return Window(active=bool(since_reset), reset_id=row.id, reset_at=row.ts)
