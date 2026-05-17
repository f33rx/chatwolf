"""TimerService implementation using the discord.py asyncio event loop.

Phase timeouts are one-shot: fire once after `delay` seconds, then done.
discord.ext.tasks is designed for repeating intervals, so we use
asyncio.create_task (which runs on the same discord event loop) to schedule
the one-shot callbacks. The DiscordTimerService class satisfies the
TimerService protocol from werewolf.core.protocols.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from typing import Any


class DiscordTimerService:
    """One-shot phase-timeout scheduler backed by asyncio tasks."""

    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Task[None]] = {}

    def schedule(self, delay: float, callback: Callable[[], Any]) -> str:
        """Schedule *callback* to fire once after *delay* seconds.

        Returns a timer_id that can be passed to cancel().
        """
        timer_id = str(uuid.uuid4())

        async def _run() -> None:
            await asyncio.sleep(delay)
            self._pending.pop(timer_id, None)
            if asyncio.iscoroutinefunction(callback):
                await callback()
            else:
                callback()

        task = asyncio.create_task(_run())
        self._pending[timer_id] = task
        return timer_id

    def cancel(self, timer_id: str) -> None:
        """Cancel a pending timer. No-op if the timer already fired."""
        task = self._pending.pop(timer_id, None)
        if task and not task.done():
            task.cancel()

    @property
    def pending_count(self) -> int:
        return len(self._pending)
