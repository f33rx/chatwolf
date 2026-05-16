"""WerewolfEngine: state machine for the Werewolf game."""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime

from pydantic import BaseModel

from werewolf.core.models import Action, GameState, Phase, Player
from werewolf.core.protocols import GameRepository

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class GameNotFoundError(Exception):
    pass


class InvalidPhaseError(Exception):
    pass


class ActionNotAllowedError(Exception):
    pass


# ---------------------------------------------------------------------------
# View models
# ---------------------------------------------------------------------------


class PublicGameState(BaseModel):
    game_id: str
    phase: Phase
    round: int
    players: list[dict]
    day_votes: dict[str, str | None]


class PrivatePlayerState(BaseModel):
    game_id: str
    player_id: str
    role: str | None
    alive: bool
    phase: Phase


# ---------------------------------------------------------------------------
# Role assignment tables
# ---------------------------------------------------------------------------

_ROLE_TABLE: dict[int, list[str]] = {
    3: ["werewolf", "seer", "villager"],
    4: ["werewolf", "seer", "villager", "villager"],
    5: ["werewolf", "werewolf", "seer", "villager", "villager"],
    6: ["werewolf", "werewolf", "seer", "villager", "villager", "villager"],
}


def _build_role_list(n: int, strategy: str) -> list[str]:
    if strategy == "vanilla":
        wolves = max(1, n // 4)
        return ["werewolf"] * wolves + ["villager"] * (n - wolves)

    if strategy == "chaos":
        wolves = max(1, random.randint(1, n // 2))  # nosec B311
        seers = 1 if n >= 3 else 0
        rest = n - wolves - seers
        return ["werewolf"] * wolves + ["seer"] * seers + ["villager"] * max(0, rest)

    # classic
    if n in _ROLE_TABLE:
        return list(_ROLE_TABLE[n])
    # 7+: 2 wolves, 1 seer, 1 hunter, 1 bodyguard, rest villagers
    base = ["werewolf", "werewolf", "seer", "hunter", "bodyguard"]
    return base + ["villager"] * (n - 5)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class WerewolfEngine:
    def __init__(self, repository: GameRepository) -> None:
        self._repo = repository

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_game(self, guild_id: str, channel_id: str) -> GameState:
        game = GameState(
            game_id=str(uuid.uuid4()),
            guild_id=guild_id,
            channel_id=channel_id,
        )
        self._repo.save_game(game)
        return game

    def join(self, game_id: str, player_id: str, display_name: str) -> GameState:
        game = self._get_or_raise(game_id)
        if game.phase != Phase.LOBBY:
            raise InvalidPhaseError("Can only join during LOBBY phase")
        if player_id in game.players:
            return game
        game.players[player_id] = Player(user_id=player_id, display_name=display_name)
        game.version += 1
        self._repo.save_game(game)
        return game

    def start(self, game_id: str) -> GameState:
        game = self._get_or_raise(game_id)
        if game.phase != Phase.LOBBY:
            raise InvalidPhaseError("Game is not in LOBBY phase")
        if len(game.players) < 3:
            raise ActionNotAllowedError("Need at least 3 players to start")

        roles = _build_role_list(len(game.players), game.role_strategy)
        random.shuffle(roles)
        for player, role in zip(game.players.values(), roles):
            player.role = role

        game.phase = Phase.FIRST_NIGHT
        game.started_at = datetime.now(UTC)
        game.version += 1
        self._repo.save_game(game)
        return game

    def vote(self, game_id: str, voter_id: str, target_id: str | None) -> GameState:
        game = self._get_or_raise(game_id)
        if game.phase != Phase.DAY:
            raise InvalidPhaseError("Voting only allowed during DAY phase")
        voter = game.players.get(voter_id)
        if voter is None or not voter.alive:
            raise ActionNotAllowedError("Voter is not an alive player in this game")

        game.day_votes[voter_id] = target_id
        game.version += 1
        self._repo.save_game(game)

        # Auto-resolve only when a specific player has strict majority —
        # noone-majority and all-voted cases are handled by explicit resolve_phase.
        if self._has_player_majority(game):
            return self.resolve_phase(game_id)

        return game

    def submit_night_action(
        self, game_id: str, actor_id: str, action: Action
    ) -> GameState:
        game = self._get_or_raise(game_id)
        if game.phase not in (Phase.FIRST_NIGHT, Phase.NIGHT):
            raise InvalidPhaseError(
                "Night actions only allowed during FIRST_NIGHT or NIGHT"
            )

        # Wolves do not kill on first night
        if game.phase == Phase.FIRST_NIGHT and action.action_type == "kill":
            raise InvalidPhaseError("Wolves cannot kill during FIRST_NIGHT")

        actor = game.players.get(actor_id)
        if actor is None or not actor.alive:
            raise ActionNotAllowedError("Actor is not an alive player in this game")

        game.pending_actions[actor_id] = action
        self._update_night_flags(game, actor, action)
        game.version += 1
        self._repo.save_game(game)

        if self._night_is_ready(game):
            return self.resolve_phase(game_id)

        return game

    def resolve_phase(self, game_id: str) -> GameState:
        """Resolve the current phase. Idempotent: no-op if conditions not met."""
        game = self._get_or_raise(game_id)

        if game.phase == Phase.FIRST_NIGHT:
            # Timer/explicit: always advance first night to DAY
            return self._resolve_first_night(game)

        if game.phase == Phase.DAY:
            # Only advance if vote conditions are met
            if self._day_is_ready(game):
                return self._resolve_day(game)
            return game

        if game.phase == Phase.NIGHT:
            # Only advance if all required night actions are in
            if self._night_is_ready(game):
                return self._resolve_night(game)
            return game

        # LOBBY and OVER: no-op
        return game

    def get_public_state(self, game_id: str) -> PublicGameState:
        game = self._get_or_raise(game_id)
        players = []
        for p in game.players.values():
            entry: dict = {
                "user_id": p.user_id,
                "display_name": p.display_name,
                "alive": p.alive,
            }
            # Reveal role only for dead players
            if not p.alive:
                entry["role"] = p.role
            players.append(entry)
        return PublicGameState(
            game_id=game.game_id,
            phase=game.phase,
            round=game.round,
            players=players,
            day_votes=dict(game.day_votes),
        )

    def get_private_state(self, game_id: str, player_id: str) -> PrivatePlayerState:
        game = self._get_or_raise(game_id)
        player = game.players.get(player_id)
        if player is None:
            raise ActionNotAllowedError("Player is not in this game")
        return PrivatePlayerState(
            game_id=game.game_id,
            player_id=player_id,
            role=player.role,
            alive=player.alive,
            phase=game.phase,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_or_raise(self, game_id: str) -> GameState:
        game = self._repo.get_game(game_id)
        if game is None:
            raise GameNotFoundError(f"Game {game_id!r} not found")
        return game

    def _update_night_flags(
        self, game: GameState, actor: Player, action: Action
    ) -> None:
        if action.action_type == "investigate":
            game.seer_checked = True
        elif action.action_type == "kill":
            game.night_kills_pending = True
        elif action.action_type == "protect":
            game.bodyguard_protected = True

    def _night_is_ready(self, game: GameState) -> bool:
        alive = [p for p in game.players.values() if p.alive]
        wolves = [p for p in alive if p.role == "werewolf"]
        seers = [p for p in alive if p.role == "seer"]

        seer_done = not seers or game.seer_checked

        if game.phase == Phase.FIRST_NIGHT:
            # Wolves hold on first night; only seer action required
            return seer_done

        wolves_done = not wolves or game.night_kills_pending
        return wolves_done and seer_done

    def _has_player_majority(self, game: GameState) -> bool:
        """True only when a specific (non-noone) player has strict majority."""
        alive = [p for p in game.players.values() if p.alive]
        threshold = len(alive) // 2 + 1
        counts: dict[str, int] = {}
        for target in game.day_votes.values():
            if target is not None:
                counts[target] = counts.get(target, 0) + 1
        return any(c >= threshold for c in counts.values())

    def _day_is_ready(self, game: GameState) -> bool:
        """True when all alive players voted or any candidate has strict majority."""
        alive = [p for p in game.players.values() if p.alive]
        alive_ids = {p.user_id for p in alive}
        voted = {vid for vid in game.day_votes if vid in alive_ids}

        # All alive players have cast a vote
        if voted == alive_ids and alive_ids:
            return True

        # Any candidate (including noone) has strict majority
        threshold = len(alive) // 2 + 1
        counts: dict[str | None, int] = {}
        for target in game.day_votes.values():
            counts[target] = counts.get(target, 0) + 1
        return any(c >= threshold for c in counts.values())

    def _check_win(self, game: GameState) -> str | None:
        alive = [p for p in game.players.values() if p.alive]
        wolves = [p for p in alive if p.role == "werewolf"]
        good = [p for p in alive if p.role != "werewolf"]

        if not wolves:
            return "villager"
        if len(wolves) >= len(good):
            return "werewolf"
        return None

    def _end_game(self, game: GameState, winner: str) -> GameState:
        game.phase = Phase.OVER
        game.ended_at = datetime.now(UTC)
        game.version += 1
        self._repo.save_game(game)
        return game

    def _resolve_first_night(self, game: GameState) -> GameState:
        game.phase = Phase.DAY
        game.round = 1
        game.pending_actions.clear()
        game.seer_checked = False
        game.bodyguard_protected = False
        game.night_kills_pending = False
        game.version += 1
        self._repo.save_game(game)
        return game

    def _resolve_day(self, game: GameState) -> GameState:
        alive = [p for p in game.players.values() if p.alive]

        # Tally votes; find strict majority for a specific player
        counts: dict[str | None, int] = {}
        for target in game.day_votes.values():
            counts[target] = counts.get(target, 0) + 1

        threshold = len(alive) // 2 + 1
        lynch_target: str | None = None
        for candidate, count in counts.items():
            if candidate is not None and count >= threshold:
                lynch_target = candidate
                break

        if lynch_target is not None:
            target_player = game.players.get(lynch_target)
            if target_player and target_player.alive:
                target_player.alive = False

        game.day_votes.clear()

        winner = self._check_win(game)
        if winner:
            return self._end_game(game, winner)

        game.phase = Phase.NIGHT
        game.round += 1
        game.pending_actions.clear()
        game.seer_checked = False
        game.bodyguard_protected = False
        game.night_kills_pending = False
        game.version += 1
        self._repo.save_game(game)
        return game

    def _resolve_night(self, game: GameState) -> GameState:
        # Find bodyguard protection target
        protected_id: str | None = None
        for action in game.pending_actions.values():
            if action.action_type == "protect" and action.target_id:
                protected_id = action.target_id
                break

        # Apply wolf kill (blocked if target is protected)
        wolf_kill_target: str | None = None
        for action in game.pending_actions.values():
            if action.action_type == "kill" and action.target_id:
                wolf_kill_target = action.target_id
                break

        if wolf_kill_target and wolf_kill_target != protected_id:
            target = game.players.get(wolf_kill_target)
            if target and target.alive:
                target.alive = False

        winner = self._check_win(game)
        if winner:
            return self._end_game(game, winner)

        game.phase = Phase.DAY
        game.round += 1
        game.pending_actions.clear()
        game.seer_checked = False
        game.bodyguard_protected = False
        game.night_kills_pending = False
        game.version += 1
        self._repo.save_game(game)
        return game
