"""The in-app sync loop: once shortly after startup, then on an interval.

Runs only while the app runs (ADR 0003). Every exception from a sync is
logged by class name and swallowed, so the loop never dies; cancellation
(app shutdown) is the only way out.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from app.commitments.enums import SyncTrigger
from app.sync.service import SyncInProgress

logger = logging.getLogger(__name__)


async def scheduler_loop(
    run_once: Callable[[str], Awaitable[object]],
    *,
    interval_seconds: float,
    startup_delay: float = 2.0,
) -> None:
    await asyncio.sleep(startup_delay)
    trigger = SyncTrigger.STARTUP
    while True:
        try:
            await run_once(trigger)
        except asyncio.CancelledError:
            raise
        except SyncInProgress:
            logger.info("scheduled %s sync skipped: a sync is already running", trigger)
        except Exception as exc:  # noqa: BLE001
            logger.warning("scheduled %s sync failed: %s", trigger, type(exc).__name__)
        trigger = SyncTrigger.INTERVAL
        await asyncio.sleep(interval_seconds)
