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
# Helpers
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
# Scenario 1: Full lobby → first night → day → night cycle
# ---------------------------------------------------------------------------


def test_full_lobby_to_night_cycle(engine, repo):
    players = {"wolf": "Wolf", "seer": "Seer", "vill": "Villager"}
    gid = _make_game(engine, players)
    game = engine.start(gid)
    assert game.phase == Phase.FIRST_NIGHT
    assert game.round == 0

    # Seer investigates on first night — triggers resolve (no wolves on first night)
    seer_id = next(uid for uid, p in game.players.items() if p.role == "seer")
    wolf_id = next(uid for uid, p in game.players.items() if p.role == "werewolf")
    villager_id = next(uid for uid, p in game.players.items() if p.role == "villager")

    action = Action(actor_id=seer_id, action_type="investigate", target_id=wolf_id)
    game = engine.submit_night_action(gid, seer_id, action)
    assert game.phase == Phase.DAY
    assert game.round == 1

    # Day: vote to lynch the wolf
    engine.vote(gid, seer_id, wolf_id)
    game = engine.vote(gid, villager_id, wolf_id)
    assert game.phase == Phase.NIGHT or game.phase == Phase.OVER

    if game.phase == Phase.NIGHT:
        assert game.round == 2


# ---------------------------------------------------------------------------
# Scenario 2: Village wins — all werewolves eliminated
# ---------------------------------------------------------------------------


def test_village_win(engine, repo):
    gid = _make_game(engine, {"wolf": "Wolf", "seer": "Seer", "vill": "Villager"})
    _force_roles(repo, gid, {"wolf": "werewolf", "seer": "seer", "vill": "villager"})

    # First night: seer investigates, resolves to DAY
    action = Action(actor_id="seer", action_type="investigate", target_id="wolf")
    game = engine.submit_night_action(gid, "seer", action)
    assert game.phase == Phase.DAY

    # Day vote: lynch the wolf — 2 of 3 alive vote wolf
    engine.vote(gid, "seer", "wolf")
    game = engine.vote(gid, "vill", "wolf")

    assert game.phase == Phase.OVER
    assert not game.players["wolf"].alive
    # Check winner stored
    game_state = repo.get_game(gid)
    assert game_state.phase == Phase.OVER


# ---------------------------------------------------------------------------
# Scenario 3: Werewolf wins — wolves outnumber villagers after night kill
# ---------------------------------------------------------------------------


def test_werewolf_win(engine, repo):
    # 3 players: 1 wolf, 1 seer, 1 villager
    # Night 1: seer investigates, transitions to DAY
    # Day 1: vote is tied — no lynch (noone majority via all-voted)
    # Night 2: wolf kills seer → wolves outnumber good → wolf win
    gid = _make_game(engine, {"wolf": "Wolf", "seer": "Seer", "vill": "Villager"})
    _force_roles(repo, gid, {"wolf": "werewolf", "seer": "seer", "vill": "villager"})

    # First night: seer investigates
    action = Action(actor_id="seer", action_type="investigate", target_id="wolf")
    game = engine.submit_night_action(gid, "seer", action)
    assert game.phase == Phase.DAY

    # Day 1: tied vote — seer votes wolf, villager votes seer, wolf votes villager
    engine.vote(gid, "seer", "wolf")
    engine.vote(gid, "vill", "seer")
    game = engine.vote(gid, "wolf", "vill")
    # All voted, no majority — no lynch, move to NIGHT
    assert game.phase == Phase.NIGHT

    # Night 2: wolf kills seer
    kill = Action(actor_id="wolf", action_type="kill", target_id="seer")
    game = engine.submit_night_action(gid, "wolf", kill)

    assert game.phase == Phase.OVER
    assert not game.players["seer"].alive


# ---------------------------------------------------------------------------
# Scenario 4: Tanner wins — tanner is lynched during day
# ---------------------------------------------------------------------------


def test_tanner_wins_when_lynched(engine, repo):
    gid = _make_game(
        engine,
        {"wolf": "Wolf", "tanner": "Tanner", "vill1": "Vill1", "vill2": "Vill2"},
    )
    _force_roles(
        repo,
        gid,
        {
            "wolf": "werewolf",
            "tanner": "tanner",
            "vill1": "villager",
            "vill2": "villager",
        },
    )

    # First night: no seer, resolve immediately
    game = engine.resolve_phase(gid)
    assert game.phase == Phase.DAY

    # Day: lynch the tanner (3 of 4 vote tanner)
    engine.vote(gid, "wolf", "tanner")
    engine.vote(gid, "vill1", "tanner")
    game = engine.vote(gid, "vill2", "tanner")

    assert game.phase == Phase.OVER
    assert not game.players["tanner"].alive
    game_state = repo.get_game(gid)
    assert game_state.phase == Phase.OVER


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

    # First night: no seer, resolve immediately
    game = engine.resolve_phase(gid)
    assert game.phase == Phase.DAY

    # Day: no majority — all vote different targets
    engine.vote(gid, "wolf", "vill")
    engine.vote(gid, "hunter", "wolf")
    game = engine.vote(gid, "vill", "hunter")
    # Tied — no lynch, night begins
    assert game.phase == Phase.NIGHT

    # Night: wolf kills hunter
    kill = Action(actor_id="wolf", action_type="kill", target_id="hunter")
    game = engine.submit_night_action(gid, "wolf", kill)

    # Phase is NIGHT (paused for hunter shot)
    assert game.phase == Phase.NIGHT
    assert game.hunter_shot_pending is True
    assert not game.players["hunter"].alive

    # Hunter fires at wolf
    game = engine.hunter_shoot(gid, "hunter", "wolf")

    assert not game.players["wolf"].alive
    # With wolf dead and only villager remaining, game should be over
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

    # First night: no seer, resolve immediately
    game = engine.resolve_phase(gid)
    assert game.phase == Phase.DAY

    # Day: lynch the hunter (3 of 4 vote hunter)
    engine.vote(gid, "wolf", "hunter")
    engine.vote(gid, "vill1", "hunter")
    game = engine.vote(gid, "vill2", "hunter")

    # Phase paused for hunter shot
    assert game.phase == Phase.DAY
    assert game.hunter_shot_pending is True
    assert not game.players["hunter"].alive

    # Hunter shoots the wolf
    game = engine.hunter_shoot(gid, "hunter", "wolf")

    assert not game.players["wolf"].alive
    # After hunter fires, game proceeds — now villagers remain, villagers win
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

    # First night: bodyguard protects self — so they can guard vill on night 2
    protect = Action(actor_id="bg", action_type="protect", target_id="bg")
    game = engine.submit_night_action(gid, "bg", protect)
    assert game.phase == Phase.DAY

    # Day: no majority, all vote differently
    engine.vote(gid, "wolf", "vill")
    engine.vote(gid, "bg", "wolf")
    game = engine.vote(gid, "vill", "bg")
    assert game.phase == Phase.NIGHT

    # Night 2: wolf targets villager, bodyguard protects villager
    kill = Action(actor_id="wolf", action_type="kill", target_id="vill")
    protect2 = Action(actor_id="bg", action_type="protect", target_id="vill")
    engine.submit_night_action(gid, "wolf", kill)
    game = engine.submit_night_action(gid, "bg", protect2)

    # Villager saved by bodyguard — villager still alive
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

    # First night: bodyguard protects villager
    protect = Action(actor_id="bg", action_type="protect", target_id="vill")
    game = engine.submit_night_action(gid, "bg", protect)
    assert game.phase == Phase.DAY

    # Advance to night 2 (vote with no majority)
    engine.vote(gid, "wolf", "vill")
    engine.vote(gid, "bg", "wolf")
    game = engine.vote(gid, "vill", "bg")
    assert game.phase == Phase.NIGHT

    # Night 2: bodyguard tries to protect same villager again
    protect_again = Action(actor_id="bg", action_type="protect", target_id="vill")
    with pytest.raises(ActionNotAllowedError):
        engine.submit_night_action(gid, "bg", protect_again)


# ---------------------------------------------------------------------------
# Scenario 9: Tie vote — no lynch, game continues to night
# ---------------------------------------------------------------------------


def test_tie_vote_no_lynch(engine, repo):
    gid = _make_game(engine, {"wolf": "Wolf", "seer": "Seer", "vill": "Villager"})
    _force_roles(repo, gid, {"wolf": "werewolf", "seer": "seer", "vill": "villager"})

    # First night: seer investigates
    action = Action(actor_id="seer", action_type="investigate", target_id="wolf")
    game = engine.submit_night_action(gid, "seer", action)
    assert game.phase == Phase.DAY

    # All vote differently — tied, no lynch
    engine.vote(gid, "seer", "wolf")
    engine.vote(gid, "vill", "seer")
    game = engine.vote(gid, "wolf", "vill")

    assert game.phase == Phase.NIGHT
    # All players still alive
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

    # All three vote noone — all-voted triggers auto-resolve
    engine.vote(gid, "seer", None)
    engine.vote(gid, "vill", None)
    game = engine.vote(gid, "wolf", None)

    # No lynch, game advances to NIGHT
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

    # No votes cast — resolve_phase should be a no-op
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

    # No hunter_shot_pending — should raise
    with pytest.raises(InvalidPhaseError):
        engine.hunter_shoot(gid, "hunter", "wolf")
