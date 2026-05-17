"""Scenario tests: full game flows through public engine API."""

from __future__ import annotations

import pytest

from werewolf.core.engine import (
    ActionNotAllowedError,
    InvalidPhaseError,
    WerewolfEngine,
)
from werewolf.core.models import Action, GameState, Phase

# ---------------------------------------------------------------------------
# In-memory repository (same as test_engine.py)
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


# ---------------------------------------------------------------------------
# Helpers: class-based test suite (_setup pattern)
# ---------------------------------------------------------------------------


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
# Helpers: standalone test suite (_make_game / _force_roles pattern)
# ---------------------------------------------------------------------------


def _make_game(engine: WerewolfEngine, players: dict[str, str]) -> str:
    """Create a game and add named players. Returns game_id."""
    game = engine.create_game("guild1", "chan1")
    gid = game.game_id
    for uid, name in players.items():
        engine.join(gid, uid, name)
    return gid


def _force_roles(repo: InMemoryRepo, game_id: str, roles: dict[str, str]) -> None:
    """Directly assign roles to players (bypasses shuffle for deterministic tests)."""
    game = repo.get_game(game_id)
    assert game is not None
    game.phase = Phase.FIRST_NIGHT
    game.round = 0
    for uid, role in roles.items():
        game.players[uid].role = role
    repo.save_game(game)


# ---------------------------------------------------------------------------
# Scenario 1: Full lobby -> FIRST_NIGHT -> DAY -> NIGHT -> DAY cycle
# ---------------------------------------------------------------------------


class TestLobbyCycle:
    def test_phases_advance_correctly(self, engine):
        # 5-player vanilla: 1 wolf, 4 villagers — no seer, so first night
        # resolves via explicit resolve_phase call
        game = _setup(engine, 5, strategy="vanilla")
        assert game.phase == Phase.FIRST_NIGHT
        gid = game.game_id

        # First night -> DAY (no seer required with vanilla)
        game = engine.resolve_phase(gid)
        assert game.phase == Phase.DAY
        assert game.round == 1

        # Day: all alive vote noone -> resolve -> NIGHT
        pids = [uid for uid, p in game.players.items() if p.alive]
        for pid in pids:
            engine.vote(gid, pid, None)
        game = engine.resolve_phase(gid)
        assert game.phase == Phase.NIGHT
        assert game.round == 2

        # Night: wolf kills one villager -> auto-resolve -> DAY
        by_role = _players_by_role(engine._repo.get_game(gid))
        wolf_id = by_role["werewolf"][0]
        target_id = by_role["villager"][0]
        game = engine.submit_night_action(
            gid,
            wolf_id,
            Action(actor_id=wolf_id, action_type="kill", target_id=target_id),
        )
        assert game.phase == Phase.DAY
        assert game.round == 2
        assert not game.players[target_id].alive

    def test_dead_player_cannot_vote(self, engine):
        game = _setup(engine, 5, strategy="vanilla")
        gid = game.game_id
        game = engine.resolve_phase(gid)  # -> DAY

        pids = [uid for uid, p in game.players.items() if p.alive]
        for pid in pids:
            engine.vote(gid, pid, None)
        engine.resolve_phase(gid)  # -> NIGHT

        by_role = _players_by_role(engine._repo.get_game(gid))
        wolf_id = by_role["werewolf"][0]
        victim_id = by_role["villager"][0]
        engine.submit_night_action(
            gid,
            wolf_id,
            Action(actor_id=wolf_id, action_type="kill", target_id=victim_id),
        )

        with pytest.raises(ActionNotAllowedError):
            engine.vote(gid, victim_id, wolf_id)


# ---------------------------------------------------------------------------
# Scenario 2: Village win — all wolves eliminated
# ---------------------------------------------------------------------------


class TestVillageWin:
    def test_village_wins_when_wolf_lynched(self, engine):
        game = _setup(engine, 3, strategy="vanilla")
        gid = game.game_id

        game = engine.resolve_phase(gid)
        assert game.phase == Phase.DAY

        by_role = _players_by_role(game)
        wolf_id = by_role["werewolf"][0]
        villager_ids = by_role["villager"]

        engine.vote(gid, villager_ids[0], wolf_id)
        game = engine.vote(gid, villager_ids[1], wolf_id)

        assert game.phase == Phase.OVER
        assert game.winner == "villager"
        assert not game.players[wolf_id].alive

    def test_all_wolves_killed_at_night_ends_game(self, engine):
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
        game = _setup(engine, 3, strategy="vanilla")
        gid = game.game_id
        game = engine.resolve_phase(gid)
        assert game.phase == Phase.DAY

        by_role = _players_by_role(game)
        wolf_id = by_role["werewolf"][0]
        villager_ids = by_role["villager"]

        engine.vote(gid, villager_ids[0], villager_ids[1])
        game = engine.vote(gid, wolf_id, villager_ids[1])

        assert game.phase == Phase.OVER
        assert game.winner == "werewolf"
        assert not game.players[villager_ids[1]].alive

    def test_wolf_wins_at_night_kill(self, engine):
        # 4-player vanilla: 1 wolf, 3 villagers
        # Mislynch day 1 -> NIGHT -> wolf kills -> 1 wolf, 1 villager -> wolf wins
        game = _setup(engine, 4, strategy="vanilla")
        gid = game.game_id
        game = engine.resolve_phase(gid)

        by_role = _players_by_role(game)
        wolf_id = by_role["werewolf"][0]
        villager_ids = by_role["villager"]

        engine.vote(gid, wolf_id, villager_ids[0])
        engine.vote(gid, villager_ids[1], villager_ids[0])
        game = engine.vote(gid, villager_ids[2], villager_ids[0])
        assert game.phase == Phase.NIGHT

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

        game = engine.submit_night_action(
            gid,
            seer_id,
            Action(actor_id=seer_id, action_type="investigate", target_id=wolf_id),
        )
        assert game.phase == Phase.DAY

        engine.vote(gid, wolf_id, tanner_id)
        engine.vote(gid, seer_id, tanner_id)
        game = engine.vote(gid, villager_id, tanner_id)

        assert game.phase == Phase.OVER
        assert game.winner == "tanner"
        assert not game.players[tanner_id].alive

    def test_tanner_does_not_win_if_killed_at_night(self, engine):
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
            Action(actor_id=seer_id, action_type="investigate", target_id=tanner_id),
        )
        assert game.phase == Phase.DAY

        for pid in [wolf_id, seer_id, tanner_id, villager_id]:
            engine.vote(gid, pid, None)
        game = engine.resolve_phase(gid)
        assert game.phase == Phase.NIGHT

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
        assert game.winner != "tanner"
        assert not game.players[tanner_id].alive

    def test_tanner_win_checked_before_wolf_win(self, engine):
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

        engine.vote(gid, wolf_id, tanner_id)
        engine.vote(gid, seer_id, tanner_id)
        game = engine.vote(gid, villager_id, tanner_id)

        assert game.winner == "tanner"


# ---------------------------------------------------------------------------
# Scenario 5: Hunter chain — hunter killed at night, fires shot
# ---------------------------------------------------------------------------


def test_hunter_chain_killed_at_night(engine, repo):
    gid = _make_game(
        engine,
        {"wolf": "Wolf", "hunter": "Hunter", "vill": "Villager"},
    )
    _force_roles(
        repo, gid, {"wolf": "werewolf", "hunter": "hunter", "vill": "villager"}
    )

    game = engine.resolve_phase(gid)
    assert game.phase == Phase.DAY

    engine.vote(gid, "wolf", "vill")
    engine.vote(gid, "hunter", "wolf")
    game = engine.vote(gid, "vill", "hunter")
    assert game.phase == Phase.NIGHT

    kill = Action(actor_id="wolf", action_type="kill", target_id="hunter")
    game = engine.submit_night_action(gid, "wolf", kill)

    assert game.phase == Phase.NIGHT
    assert game.hunter_shot_pending is True
    assert not game.players["hunter"].alive

    game = engine.hunter_shoot(gid, "hunter", "wolf")

    assert not game.players["wolf"].alive
    assert game.phase == Phase.OVER


# ---------------------------------------------------------------------------
# Scenario 6: Hunter chain — hunter lynched during day, fires shot
# ---------------------------------------------------------------------------


def test_hunter_chain_lynched_during_day(engine, repo):
    gid = _make_game(
        engine,
        {"wolf": "Wolf", "hunter": "Hunter", "vill1": "Vill1", "vill2": "Vill2"},
    )
    _force_roles(
        repo,
        gid,
        {
            "wolf": "werewolf",
            "hunter": "hunter",
            "vill1": "villager",
            "vill2": "villager",
        },
    )

    game = engine.resolve_phase(gid)
    assert game.phase == Phase.DAY

    engine.vote(gid, "wolf", "hunter")
    engine.vote(gid, "vill1", "hunter")
    game = engine.vote(gid, "vill2", "hunter")

    assert game.phase == Phase.DAY
    assert game.hunter_shot_pending is True
    assert not game.players["hunter"].alive

    game = engine.hunter_shoot(gid, "hunter", "wolf")

    assert not game.players["wolf"].alive
    assert game.phase == Phase.OVER


# ---------------------------------------------------------------------------
# Scenario 7: Bodyguard saves wolf's target
# ---------------------------------------------------------------------------


def test_bodyguard_saves_target(engine, repo):
    gid = _make_game(
        engine,
        {"wolf": "Wolf", "bg": "Bodyguard", "vill": "Villager"},
    )
    _force_roles(repo, gid, {"wolf": "werewolf", "bg": "bodyguard", "vill": "villager"})

    protect = Action(actor_id="bg", action_type="protect", target_id="bg")
    game = engine.submit_night_action(gid, "bg", protect)
    assert game.phase == Phase.DAY

    engine.vote(gid, "wolf", "vill")
    engine.vote(gid, "bg", "wolf")
    game = engine.vote(gid, "vill", "bg")
    assert game.phase == Phase.NIGHT

    kill = Action(actor_id="wolf", action_type="kill", target_id="vill")
    protect2 = Action(actor_id="bg", action_type="protect", target_id="vill")
    engine.submit_night_action(gid, "wolf", kill)
    game = engine.submit_night_action(gid, "bg", protect2)

    assert game.players["vill"].alive
    assert game.phase == Phase.DAY


# ---------------------------------------------------------------------------
# Scenario 8: Bodyguard cannot guard same player two nights in a row
# ---------------------------------------------------------------------------


def test_bodyguard_cannot_repeat_guard(engine, repo):
    gid = _make_game(
        engine,
        {"wolf": "Wolf", "bg": "Bodyguard", "vill": "Villager"},
    )
    _force_roles(repo, gid, {"wolf": "werewolf", "bg": "bodyguard", "vill": "villager"})

    protect = Action(actor_id="bg", action_type="protect", target_id="vill")
    game = engine.submit_night_action(gid, "bg", protect)
    assert game.phase == Phase.DAY

    engine.vote(gid, "wolf", "vill")
    engine.vote(gid, "bg", "wolf")
    game = engine.vote(gid, "vill", "bg")
    assert game.phase == Phase.NIGHT

    protect_again = Action(actor_id="bg", action_type="protect", target_id="vill")
    with pytest.raises(ActionNotAllowedError):
        engine.submit_night_action(gid, "bg", protect_again)


# ---------------------------------------------------------------------------
# Scenario 9: Tie vote — no lynch, game continues to night
# ---------------------------------------------------------------------------


def test_tie_vote_no_lynch(engine, repo):
    gid = _make_game(engine, {"wolf": "Wolf", "seer": "Seer", "vill": "Villager"})
    _force_roles(repo, gid, {"wolf": "werewolf", "seer": "seer", "vill": "villager"})

    action = Action(actor_id="seer", action_type="investigate", target_id="wolf")
    game = engine.submit_night_action(gid, "seer", action)
    assert game.phase == Phase.DAY

    engine.vote(gid, "seer", "wolf")
    engine.vote(gid, "vill", "seer")
    game = engine.vote(gid, "wolf", "vill")

    assert game.phase == Phase.NIGHT
    assert all(p.alive for p in game.players.values())


# ---------------------------------------------------------------------------
# Scenario 10: Vote noone — explicit no-lynch
# ---------------------------------------------------------------------------


def test_vote_noone_no_lynch(engine, repo):
    gid = _make_game(engine, {"wolf": "Wolf", "seer": "Seer", "vill": "Villager"})
    _force_roles(repo, gid, {"wolf": "werewolf", "seer": "seer", "vill": "villager"})

    action = Action(actor_id="seer", action_type="investigate", target_id="wolf")
    game = engine.submit_night_action(gid, "seer", action)
    assert game.phase == Phase.DAY

    engine.vote(gid, "seer", None)
    engine.vote(gid, "vill", None)
    game = engine.vote(gid, "wolf", None)

    assert game.phase == Phase.NIGHT
    assert all(p.alive for p in game.players.values())


# ---------------------------------------------------------------------------
# Scenario 11: resolve_phase is idempotent when conditions not met
# ---------------------------------------------------------------------------


def test_resolve_phase_idempotent_day_no_votes(engine, repo):
    gid = _make_game(engine, {"wolf": "Wolf", "seer": "Seer", "vill": "Villager"})
    _force_roles(repo, gid, {"wolf": "werewolf", "seer": "seer", "vill": "villager"})

    action = Action(actor_id="seer", action_type="investigate", target_id="wolf")
    game = engine.submit_night_action(gid, "seer", action)
    assert game.phase == Phase.DAY

    game2 = engine.resolve_phase(gid)
    assert game2.phase == Phase.DAY


# ---------------------------------------------------------------------------
# Scenario 12: hunter_shoot validates state
# ---------------------------------------------------------------------------


def test_hunter_shoot_requires_pending_flag(engine, repo):
    gid = _make_game(engine, {"wolf": "Wolf", "hunter": "Hunter", "vill": "Villager"})
    _force_roles(
        repo, gid, {"wolf": "werewolf", "hunter": "hunter", "vill": "villager"}
    )

    game = engine.resolve_phase(gid)
    assert game.phase == Phase.DAY

    with pytest.raises(InvalidPhaseError):
        engine.hunter_shoot(gid, "hunter", "wolf")


# ---------------------------------------------------------------------------
# Scenario 13: resolve_phase called twice in DAY — idempotent
# ---------------------------------------------------------------------------


def test_resolve_phase_double_call_day_is_idempotent(engine, repo):
    gid = _make_game(engine, {"wolf": "Wolf", "seer": "Seer", "vill": "Villager"})
    _force_roles(repo, gid, {"wolf": "werewolf", "seer": "seer", "vill": "villager"})

    action = Action(actor_id="seer", action_type="investigate", target_id="wolf")
    engine.submit_night_action(gid, "seer", action)

    game1 = engine.resolve_phase(gid)
    game2 = engine.resolve_phase(gid)
    assert game1.phase == Phase.DAY
    assert game2.phase == Phase.DAY
    assert all(p.alive for p in game2.players.values())


# ---------------------------------------------------------------------------
# Scenario 14: resolve_phase called twice in NIGHT — idempotent
# ---------------------------------------------------------------------------


def test_resolve_phase_double_call_night_is_idempotent(engine, repo):
    gid = _make_game(engine, {"wolf": "Wolf", "seer": "Seer", "vill": "Villager"})
    _force_roles(repo, gid, {"wolf": "werewolf", "seer": "seer", "vill": "villager"})

    action = Action(actor_id="seer", action_type="investigate", target_id="wolf")
    engine.submit_night_action(gid, "seer", action)
    engine.vote(gid, "seer", "wolf")
    engine.vote(gid, "vill", "seer")
    engine.vote(gid, "wolf", "vill")

    game = repo.get_game(gid)
    assert game is not None
    assert game.phase == Phase.NIGHT

    game1 = engine.resolve_phase(gid)
    game2 = engine.resolve_phase(gid)
    assert game1.phase == Phase.NIGHT
    assert game2.phase == Phase.NIGHT
    assert all(p.alive for p in game2.players.values())


# ---------------------------------------------------------------------------
# Scenario 15: Hunter shot fires before win check
# ---------------------------------------------------------------------------


def test_hunter_shot_prevents_premature_wolf_win(engine, repo):
    # wolf=1, hunter=1, vill=1. After wolf kills hunter: alive = wolf + vill
    # wolf would win, but hunter fires first killing wolf.
    gid = _make_game(engine, {"wolf": "Wolf", "hunter": "Hunter", "vill": "Villager"})
    _force_roles(
        repo, gid, {"wolf": "werewolf", "hunter": "hunter", "vill": "villager"}
    )

    engine.resolve_phase(gid)

    engine.vote(gid, "wolf", "vill")
    engine.vote(gid, "hunter", "wolf")
    engine.vote(gid, "vill", "hunter")

    kill = Action(actor_id="wolf", action_type="kill", target_id="hunter")
    game = engine.submit_night_action(gid, "wolf", kill)
    assert game.phase == Phase.NIGHT
    assert game.hunter_shot_pending is True
    assert not game.players["hunter"].alive

    game = engine.hunter_shoot(gid, "hunter", "wolf")
    assert not game.players["wolf"].alive
    assert game.phase == Phase.OVER


# ---------------------------------------------------------------------------
# Scenario 16: Bodyguard directly saves wolf's first target on night 2
# ---------------------------------------------------------------------------


def test_bodyguard_saves_wolf_target_night2(engine, repo):
    gid = _make_game(
        engine,
        {"wolf": "Wolf", "bg": "Bodyguard", "seer": "Seer", "vill": "Villager"},
    )
    _force_roles(
        repo,
        gid,
        {"wolf": "werewolf", "bg": "bodyguard", "seer": "seer", "vill": "villager"},
    )

    investigate = Action(actor_id="seer", action_type="investigate", target_id="wolf")
    protect = Action(actor_id="bg", action_type="protect", target_id="bg")
    engine.submit_night_action(gid, "bg", protect)
    game = engine.submit_night_action(gid, "seer", investigate)
    assert game.phase == Phase.DAY

    engine.vote(gid, "wolf", "seer")
    engine.vote(gid, "seer", "wolf")
    engine.vote(gid, "bg", "vill")
    game = engine.vote(gid, "vill", "bg")
    assert game.phase == Phase.NIGHT

    kill = Action(actor_id="wolf", action_type="kill", target_id="seer")
    guard = Action(actor_id="bg", action_type="protect", target_id="seer")
    engine.submit_night_action(gid, "wolf", kill)
    game = engine.submit_night_action(gid, "bg", guard)

    assert game.players["seer"].alive
