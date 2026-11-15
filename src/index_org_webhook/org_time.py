from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

DAY_ABBR = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def recorded_at_datetime(recorded_at_ms: str | int | None, timezone: str) -> datetime:
    tz = ZoneInfo(timezone)
    if recorded_at_ms in (None, ""):
        return datetime.now(tz)
    millis = int(recorded_at_ms)
    return datetime.fromtimestamp(millis / 1000, tz=tz)


def org_inactive_timestamp(dt: datetime) -> str:
    return f"[{dt:%Y-%m-%d} {DAY_ABBR[dt.weekday()]} {dt:%H:%M}]"
