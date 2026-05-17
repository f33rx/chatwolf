"""Unit tests for DiscordTimerService."""

from __future__ import annotations

import asyncio

import pytest

from werewolf.core.protocols import TimerService
from werewolf.discord.timer import DiscordTimerService


def test_discord_timer_satisfies_protocol():
    assert isinstance(DiscordTimerService(), TimerService)


@pytest.mark.asyncio
async def test_schedule_fires_callback():
    fired = []
    timer = DiscordTimerService()

    timer.schedule(0.01, lambda: fired.append(1))
    await asyncio.sleep(0.05)

    assert fired == [1]


@pytest.mark.asyncio
async def test_schedule_returns_timer_id():
    timer = DiscordTimerService()
    tid = timer.schedule(10, lambda: None)
    assert isinstance(tid, str) and len(tid) > 0
    timer.cancel(tid)


@pytest.mark.asyncio
async def test_cancel_prevents_callback():
    fired = []
    timer = DiscordTimerService()

    tid = timer.schedule(0.5, lambda: fired.append(1))
    timer.cancel(tid)
    await asyncio.sleep(0.6)

    assert fired == []


@pytest.mark.asyncio
async def test_cancel_is_noop_after_fire():
    timer = DiscordTimerService()
    tid = timer.schedule(0.01, lambda: None)
    await asyncio.sleep(0.05)
    timer.cancel(tid)  # should not raise


@pytest.mark.asyncio
async def test_cancel_unknown_id_is_noop():
    timer = DiscordTimerService()
    timer.cancel("no-such-id")  # should not raise


@pytest.mark.asyncio
async def test_multiple_independent_timers():
    results = []
    timer = DiscordTimerService()

    timer.schedule(0.01, lambda: results.append("a"))
    timer.schedule(0.02, lambda: results.append("b"))
    await asyncio.sleep(0.06)

    assert set(results) == {"a", "b"}


@pytest.mark.asyncio
async def test_pending_count_tracks_active_timers():
    timer = DiscordTimerService()
    assert timer.pending_count == 0

    tid = timer.schedule(10, lambda: None)
    assert timer.pending_count == 1

    timer.cancel(tid)
    assert timer.pending_count == 0


@pytest.mark.asyncio
async def test_async_callback_is_awaited():
    fired = []
    timer = DiscordTimerService()

    async def _cb() -> None:
        fired.append("async")

    timer.schedule(0.01, _cb)
    await asyncio.sleep(0.05)

    assert fired == ["async"]
