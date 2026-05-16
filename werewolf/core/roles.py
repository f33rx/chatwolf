"""Role base class and concrete v1 roles: Villager, Werewolf."""

from __future__ import annotations

from abc import ABC, abstractmethod

from werewolf.core.events import GameEvent, WolvesRevealed
from werewolf.core.models import GameState, Phase, Player


class Role(ABC):
    name: str

    @abstractmethod
    def on_phase_start(self, game: GameState) -> list[GameEvent]: ...

    @abstractmethod
    def on_death(self, game: GameState, player: Player) -> list[GameEvent]: ...

    @abstractmethod
    def validate_action(
        self, game: GameState, actor: Player, target: Player | None
    ) -> bool: ...


class Villager(Role):
    name = "villager"

    def on_phase_start(self, game: GameState) -> list[GameEvent]:
        return []

    def on_death(self, game: GameState, player: Player) -> list[GameEvent]:
        return []

    def validate_action(
        self, game: GameState, actor: Player, target: Player | None
    ) -> bool:
        return False


class Werewolf(Role):
    name = "werewolf"

    def on_phase_start(self, game: GameState) -> list[GameEvent]:
        if game.phase != Phase.FIRST_NIGHT:
            return []
        wolf_ids = [
            pid for pid, p in game.players.items() if p.role == "werewolf" and p.alive
        ]
        return [WolvesRevealed(game_id=game.game_id, wolf_ids=wolf_ids)]

    def on_death(self, game: GameState, player: Player) -> list[GameEvent]:
        return []

    def validate_action(
        self, game: GameState, actor: Player, target: Player | None
    ) -> bool:
        if game.phase not in (Phase.FIRST_NIGHT, Phase.NIGHT):
            return False
        if not actor.alive:
            return False
        if target is None:
            return False
        if not target.alive:
            return False
        if actor.user_id == target.user_id:
            return False
        return True
