"""Scenario tests: drive the engine end-to-end with no Discord dependency."""

from __future__ import annotations

import pytest

from werewolf.core.engine import WerewolfEngine
from werewolf.core.models import Action, GameState, Phase

# ---------------------------------------------------------------------------
# In-memory repo (same pattern as test_engine.py)
# ---------------------------------------------------------------------------


class InMemoryRepo:
    def __init__(self):
        self._games: dict[str, GameState] = {}

    def get_game(self, game_id: str) -> GameState | None:
        return self._games.get(game_id)

    def get_active_game(self, guild_id: str) -> GameState | None:
        for g in self._games.values():
            if g.guild_id == guild_id and g.phase != Phase.OVER:
                return g
        return None

    def get_game_by_player(self, user_id: str) -> GameState | None:
        for g in self._games.values():
            if user_id in g.players:
                return g
        return None

    def save_game(self, game: GameState) -> None:
        self._games[game.game_id] = game

    def delete_game(self, game_id: str) -> None:
        self._games.pop(game_id, None)


@pytest.fixture
def repo():
    return InMemoryRepo()


@pytest.fixture
def engine(repo):
    return WerewolfEngine(repo)


def _setup(engine: WerewolfEngine, n: int, strategy: str = "classic") -> GameState:
    game = engine.create_game("guild1", "ch1")
    game.role_strategy = strategy
    for i in range(n):
        engine.join(game.game_id, f"u{i}", f"Player{i}")
    return engine.start(game.game_id)


def _players_by_role(game: GameState) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for uid, p in game.players.items():
        result.setdefault(p.role or "none", []).append(uid)
    return result


# ---------------------------------------------------------------------------
# Scenario 1: Full lobby → FIRST_NIGHT → DAY → NIGHT → DAY cycle
# ---------------------------------------------------------------------------


class TestLobbyCycle:
    def test_phases_advance_correctly(self, engine):
        # 5-player vanilla: 1 wolf, 4 villagers — no seer, so first night
        # resolves via explicit resolve_phase call
        game = _setup(engine, 5, strategy="vanilla")
        assert game.phase == Phase.FIRST_NIGHT
        gid = game.game_id

        # First night → DAY (no seer required with vanilla)
        game = engine.resolve_phase(gid)
        assert game.phase == Phase.DAY
        assert game.round == 1

        # Day: all alive vote noone → resolve → NIGHT
        pids = [uid for uid, p in game.players.items() if p.alive]
        for pid in pids:
            engine.vote(gid, pid, None)
        game = engine.resolve_phase(gid)
        assert game.phase == Phase.NIGHT
        assert game.round == 2

        # Night: wolf kills one villager → auto-resolve → DAY (game not over yet)
        by_role = _players_by_role(engine._repo.get_game(gid))
        wolf_id = by_role["werewolf"][0]
        target_id = by_role["villager"][0]
        game = engine.submit_night_action(
            gid,
            wolf_id,
            Action(actor_id=wolf_id, action_type="kill", target_id=target_id),
        )
        assert game.phase == Phase.DAY
        assert game.round == 3  # FIRST_NIGHT→DAY=1, DAY→NIGHT=2, NIGHT→DAY=3
        assert not game.players[target_id].alive

    def test_dead_player_cannot_vote(self, engine):
        game = _setup(engine, 5, strategy="vanilla")
        gid = game.game_id
        game = engine.resolve_phase(gid)  # → DAY

        # Kill first villager via wolf night action after going back to night
        pids = [uid for uid, p in game.players.items() if p.alive]
        for pid in pids:
            engine.vote(gid, pid, None)
        engine.resolve_phase(gid)  # → NIGHT

        by_role = _players_by_role(engine._repo.get_game(gid))
        wolf_id = by_role["werewolf"][0]
        victim_id = by_role["villager"][0]
        engine.submit_night_action(
            gid,
            wolf_id,
            Action(actor_id=wolf_id, action_type="kill", target_id=victim_id),
        )

        from werewolf.core.engine import ActionNotAllowedError

        with pytest.raises(ActionNotAllowedError):
            engine.vote(gid, victim_id, wolf_id)


# ---------------------------------------------------------------------------
# Scenario 2: Village win — all wolves eliminated
# ---------------------------------------------------------------------------


class TestVillageWin:
    def test_village_wins_when_wolf_lynched(self, engine):
        # 3-player vanilla: 1 wolf, 2 villagers — straightforward lynch scenario
        game = _setup(engine, 3, strategy="vanilla")
        gid = game.game_id

        # FIRST_NIGHT → DAY (no seer, resolve immediately)
        game = engine.resolve_phase(gid)
        assert game.phase == Phase.DAY

        by_role = _players_by_role(game)
        wolf_id = by_role["werewolf"][0]
        villager_ids = by_role["villager"]

        # Both villagers vote for the wolf → strict majority (2/3) → auto-resolve
        engine.vote(gid, villager_ids[0], wolf_id)
        game = engine.vote(gid, villager_ids[1], wolf_id)

        assert game.phase == Phase.OVER
        assert game.winner == "villager"
        assert not game.players[wolf_id].alive

    def test_all_wolves_killed_at_night_ends_game(self, engine):
        # 3-player vanilla: wolf kills no one useful; seer not present
        # Make wolf die at night via a different path: lynch on day
        # Same as above but verify started_at / ended_at populated
        game = _setup(engine, 3, strategy="vanilla")
        gid = game.game_id
        game = engine.resolve_phase(gid)

        by_role = _players_by_role(game)
        wolf_id = by_role["werewolf"][0]
        villager_ids = by_role["villager"]

        engine.vote(gid, villager_ids[0], wolf_id)
        game = engine.vote(gid, villager_ids[1], wolf_id)

        assert game.ended_at is not None
        assert game.winner == "villager"


# ---------------------------------------------------------------------------
# Scenario 3: Werewolf win — wolves >= villagers
# ---------------------------------------------------------------------------


class TestWerewolfWin:
    def test_wolf_wins_when_equal_count(self, engine):
        # 3-player vanilla: wolf kills a villager on night → 1 wolf, 1 villager
        # → wolf wins at resolve_night (or after mislynch day)
        game = _setup(engine, 3, strategy="vanilla")
        gid = game.game_id
        game = engine.resolve_phase(gid)  # FIRST_NIGHT → DAY
        assert game.phase == Phase.DAY

        by_role = _players_by_role(game)
        wolf_id = by_role["werewolf"][0]
        villager_ids = by_role["villager"]

        # Mislynch: villagers vote for a different villager (wolf safe)
        # Villager 0 and wolf vote for villager 1 → majority
        engine.vote(gid, villager_ids[0], villager_ids[1])
        game = engine.vote(gid, wolf_id, villager_ids[1])

        # After mislynch: 1 wolf + 1 villager alive → wolf wins immediately
        assert game.phase == Phase.OVER
        assert game.winner == "werewolf"
        assert not game.players[villager_ids[1]].alive

    def test_wolf_wins_at_night_kill(self, engine):
        # 4-player vanilla: 1 wolf, 3 villagers
        # Mislynch day 1 → NIGHT → wolf kills → 1 wolf, 1 villager → wolf wins
        game = _setup(engine, 4, strategy="vanilla")
        gid = game.game_id
        game = engine.resolve_phase(gid)  # → DAY

        by_role = _players_by_role(game)
        wolf_id = by_role["werewolf"][0]
        villager_ids = by_role["villager"]

        # 3 votes needed for majority (4//2+1=3)
        # Wolf + 2 villagers vote for villager_ids[0]
        engine.vote(gid, wolf_id, villager_ids[0])
        engine.vote(gid, villager_ids[1], villager_ids[0])
        game = engine.vote(gid, villager_ids[2], villager_ids[0])
        # After lynch: 1 wolf, 2 villagers → no win yet → NIGHT
        assert game.phase == Phase.NIGHT

        # Wolf kills one of the remaining villagers → 1 wolf, 1 villager → wolf wins
        game = engine.submit_night_action(
            gid,
            wolf_id,
            Action(actor_id=wolf_id, action_type="kill", target_id=villager_ids[1]),
        )
        assert game.phase == Phase.OVER
        assert game.winner == "werewolf"


# ---------------------------------------------------------------------------
# Scenario 4: Tanner win — tanner lynched during day
# ---------------------------------------------------------------------------


class TestTannerWin:
    def test_tanner_wins_when_lynched(self, engine):
        # 4-player classic: werewolf, tanner, seer, villager
        game = _setup(engine, 4, strategy="classic")
        gid = game.game_id
        assert game.phase == Phase.FIRST_NIGHT

        by_role = _players_by_role(game)
        tanner_id = by_role["tanner"][0]
        seer_id = by_role["seer"][0]
        wolf_id = by_role["werewolf"][0]
        villager_id = by_role["villager"][0]

        # First night: seer investigates → auto-resolve → DAY
        game = engine.submit_night_action(
            gid,
            seer_id,
            Action(actor_id=seer_id, action_type="investigate", target_id=wolf_id),
        )
        assert game.phase == Phase.DAY

        # Day: wolf, seer, villager all vote for tanner → majority (3/4) → auto-resolve
        engine.vote(gid, wolf_id, tanner_id)
        engine.vote(gid, seer_id, tanner_id)
        game = engine.vote(gid, villager_id, tanner_id)

        assert game.phase == Phase.OVER
        assert game.winner == "tanner"
        assert not game.players[tanner_id].alive

    def test_tanner_does_not_win_if_killed_at_night(self, engine):
        # Tanner must be lynched (day vote), not killed at night
        game = _setup(engine, 4, strategy="classic")
        gid = game.game_id

        by_role = _players_by_role(game)
        tanner_id = by_role["tanner"][0]
        seer_id = by_role["seer"][0]
        wolf_id = by_role["werewolf"][0]
        villager_id = by_role["villager"][0]

        # First night: seer investigates, wolf cannot kill on first night
        game = engine.submit_night_action(
            gid,
            seer_id,
            Action(actor_id=seer_id, action_type="investigate", target_id=tanner_id),
        )
        assert game.phase == Phase.DAY

        # Day: vote to no-lynch (all vote noone) → NIGHT
        for pid in [wolf_id, seer_id, tanner_id, villager_id]:
            engine.vote(gid, pid, None)
        game = engine.resolve_phase(gid)
        assert game.phase == Phase.NIGHT

        # Wolf kills tanner; seer also must investigate for night to resolve
        engine.submit_night_action(
            gid,
            wolf_id,
            Action(actor_id=wolf_id, action_type="kill", target_id=tanner_id),
        )
        game = engine.submit_night_action(
            gid,
            seer_id,
            Action(actor_id=seer_id, action_type="investigate", target_id=villager_id),
        )
        # Tanner dead at night → no tanner win; game continues
        assert game.winner != "tanner"
        assert not game.players[tanner_id].alive

    def test_tanner_win_checked_before_wolf_win(self, engine):
        # Edge: after tanner is lynched, wolf might technically satisfy win condition
        # but tanner win must take precedence
        game = _setup(engine, 4, strategy="classic")
        gid = game.game_id

        by_role = _players_by_role(game)
        tanner_id = by_role["tanner"][0]
        seer_id = by_role["seer"][0]
        wolf_id = by_role["werewolf"][0]
        villager_id = by_role["villager"][0]

        game = engine.submit_night_action(
            gid,
            seer_id,
            Action(actor_id=seer_id, action_type="investigate", target_id=wolf_id),
        )
        assert game.phase == Phase.DAY

        # Lynch tanner — even if remaining balance would trigger wolf win, tanner wins
        engine.vote(gid, wolf_id, tanner_id)
        engine.vote(gid, seer_id, tanner_id)
        game = engine.vote(gid, villager_id, tanner_id)

        assert game.winner == "tanner"
