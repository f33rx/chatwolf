"""Abstract Protocol interfaces: seams between core engine and infrastructure."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    pass


@runtime_checkable
class GameRepository(Protocol):
    """Persistence seam for game state."""

    def get_game(self, game_id: str) -> Any | None: ...

    def get_active_game(self, guild_id: str) -> Any | None: ...

    def get_game_by_player(self, user_id: str) -> Any | None: ...

    def save_game(self, game: Any) -> None: ...

    def delete_game(self, game_id: str) -> None: ...


@runtime_checkable
class TimerService(Protocol):
    """Scheduling seam for delayed callbacks."""

    def schedule(self, delay: float, callback: Any) -> str: ...

    def cancel(self, timer_id: str) -> None: ...


@runtime_checkable
class MessagingProtocol(Protocol):
    """Messaging seam for sending to channels and DMs."""

    async def send_channel(self, channel_id: int, message: str) -> None: ...

    async def send_dm(self, user_id: int, message: str) -> None: ...
