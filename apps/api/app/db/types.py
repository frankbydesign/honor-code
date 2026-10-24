"""Column types that behave the same on SQLite and Postgres.

Use UTCDateTime for every timestamp column. SQLite has no timezone-aware
datetime type, so a plain DateTime(timezone=True) comes back naive and then
can't be compared with datetime.now(timezone.utc). This decorator stores UTC
and re-attaches the UTC tzinfo on the way out, on any dialect.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator[datetime]):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError(
                "naive datetime written to a UTCDateTime column; "
                "use datetime.now(timezone.utc) or attach a tzinfo"
            )
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
