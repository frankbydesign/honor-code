"""The in-app sync loop keeps going through failures and stops on cancel."""

from __future__ import annotations

import asyncio

import pytest

from app.sync.scheduler import scheduler_loop
from app.sync.service import SyncInProgress


async def _wait_for(predicate, timeout=2.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.005)


async def test_loop_runs_startup_then_interval_and_survives_errors():
    calls = []

    async def run_once(trigger):
        calls.append(trigger)
        if len(calls) == 1:
            raise RuntimeError("first run blew up")
        if len(calls) == 2:
            raise SyncInProgress()

    task = asyncio.create_task(scheduler_loop(run_once, interval_seconds=0, startup_delay=0))
    await _wait_for(lambda: len(calls) >= 4)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert calls[0] == "startup"
    assert set(calls[1:]) == {"interval"}


async def test_loop_stops_cleanly_while_sleeping():
    calls = []

    async def run_once(trigger):
        calls.append(trigger)

    task = asyncio.create_task(scheduler_loop(run_once, interval_seconds=3600, startup_delay=0))
    await _wait_for(lambda: calls == ["startup"])
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.done()


async def test_errors_are_logged_without_their_message(caplog):
    calls = []

    async def run_once(trigger):
        calls.append(trigger)
        raise RuntimeError("transcript text ZQX-SENTINEL-88")

    task = asyncio.create_task(scheduler_loop(run_once, interval_seconds=0, startup_delay=0))
    await _wait_for(lambda: len(calls) >= 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert "RuntimeError" in caplog.text
    assert "ZQX-SENTINEL-88" not in caplog.text
