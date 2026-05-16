"""Role definitions for Werewolf game."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from werewolf.core.events import GameEvent
    from werewolf.core.models import GameState, Player

_WOLF_ALIGNED: frozenset[str] = frozenset({"werewolf", "lycan"})


# ---------------------------------------------------------------------------
# Abstract base (fury's Role ABC)
# ---------------------------------------------------------------------------


class Role(ABC):
    name: str
    alignment: str

    def on_phase_start(self, game: GameState, player: Player) -> list[GameEvent]:
        return []

    def on_death(self, game: GameState, player: Player) -> list[GameEvent]:
        return []

    @abstractmethod
    def validate_action(
        self, game: GameState, actor: Player, target: Player
    ) -> bool: ...


# ---------------------------------------------------------------------------
# Villager-aligned roles (fury's instance-method classes)
# ---------------------------------------------------------------------------


class Villager(Role):
    name = "villager"
    alignment = "villager"

    def validate_action(self, game: GameState, actor: Player, target: Player) -> bool:
        return False


class Werewolf(Role):
    name = "werewolf"
    alignment = "werewolf"

    def on_phase_start(self, game: GameState, player: Player) -> list[GameEvent]:
        from werewolf.core.events import WolvesRevealed
        from werewolf.core.models import Phase

        if game.phase == Phase.FIRST_NIGHT:
            wolf_ids = [
                p.user_id
                for p in game.players.values()
                if p.role == "werewolf" and p.alive
            ]
            return [WolvesRevealed(game_id=game.game_id, wolf_ids=wolf_ids)]
        return []

    def validate_action(self, game: GameState, actor: Player, target: Player) -> bool:
        return target.alive and target.role != "werewolf"


# ---------------------------------------------------------------------------
# Static-method roles (guzzle's plain classes)
# ---------------------------------------------------------------------------


class Seer:
    name = "seer"
    alignment = "villager"

    @staticmethod
    def investigate(target_role: str) -> str:
        return "wolf" if target_role in _WOLF_ALIGNED else "villager"


class Hunter:
    name = "hunter"
    alignment = "villager"

    @staticmethod
    def on_death(game: GameState, shot_target_id: str) -> None:
        target = game.players.get(shot_target_id)
        if target and target.alive:
            target.alive = False


class Bodyguard:
    name = "bodyguard"
    alignment = "villager"

    @staticmethod
    def can_protect(game: GameState, target_id: str) -> bool:
        return target_id != game.last_guarded_user_id

    @staticmethod
    def record_protection(game: GameState, target_id: str) -> None:
        game.last_guarded_user_id = target_id


class Tanner:
    name = "tanner"
    alignment = "neutral"
