"""Phase 1 settings: the external services and the sync schedule.

Unlike app.auth.config, none of these is required at startup. A missing
API key turns into a readable "not configured" answer from the endpoint
that needs it, so the app still starts and you can see what is missing.
Values are read on each call, which keeps them easy to change in tests.

LOCAL_TIMEZONE is the exception that is checked at startup (see
validate()), because a typo there would silently shift every meeting date.
"""

from __future__ import annotations

import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_EXTRACTION_MODEL = "claude-sonnet-5-5"
DEFAULT_TIMEZONE = "America/Los_Angeles"


def _get(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def _int(name: str, default: int, minimum: int) -> int:
    raw = _get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise RuntimeError(f"{name} must be a whole number (got {raw!r})") from None
    if value < minimum:
        raise RuntimeError(f"{name} must be at least {minimum} (got {value})")
    return value


def anthropic_api_key() -> str | None:
    return _get("ANTHROPIC_API_KEY")


def fathom_api_key() -> str | None:
    return _get("FATHOM_API_KEY")


def extraction_model() -> str:
    return _get("EXTRACTION_MODEL") or DEFAULT_EXTRACTION_MODEL


def extraction_timeout_seconds() -> int:
    return _int("EXTRACTION_TIMEOUT_SECONDS", 120, 1)


def fathom_backfill_days() -> int:
    return _int("FATHOM_BACKFILL_DAYS", 14, 1)


def fathom_sync_interval_minutes() -> int:
    return _int("FATHOM_SYNC_INTERVAL_MINUTES", 30, 1)


def sync_enabled() -> bool:
    return (_get("SYNC_ENABLED") or "true").lower() not in {"0", "false", "no", "off"}


def local_timezone() -> ZoneInfo:
    name = _get("LOCAL_TIMEZONE") or DEFAULT_TIMEZONE
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise RuntimeError(
            f"LOCAL_TIMEZONE is not a known IANA time zone (got {name!r}); "
            "use a name like America/Los_Angeles"
        ) from None


def missing_for_sync() -> list[str]:
    """The variables a Fathom sync needs that are not set, in a stable order."""
    missing = []
    if fathom_api_key() is None:
        missing.append("FATHOM_API_KEY")
    if anthropic_api_key() is None:
        missing.append("ANTHROPIC_API_KEY")
    return missing


def validate() -> None:
    """Called once at startup. Raises RuntimeError naming the bad variable."""
    local_timezone()
    extraction_timeout_seconds()
    fathom_backfill_days()
    fathom_sync_interval_minutes()
