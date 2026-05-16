"""Unit tests for WerewolfEngine state machine."""

from __future__ import annotations

import pytest

from werewolf.core.engine import (
    ActionNotAllowedError,
    GameNotFoundError,
    InvalidPhaseError,
    PrivatePlayerState,
    PublicGameState,
    WerewolfEngine,
)
from werewolf.core.models import Action, GameState, Phase

# ---------------------------------------------------------------------------
# Minimal in-memory repository for testing
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


def _add_players(engine: WerewolfEngine, game_id: str, n: int) -> None:
    for i in range(n):
        engine.join(game_id, f"u{i}", f"Player{i}")


# ---------------------------------------------------------------------------
# create_game
# ---------------------------------------------------------------------------


class TestCreateGame:
    def test_returns_gamestate_in_lobby(self, engine):
        state = engine.create_game("guild1", "chan1")
        assert state.phase == Phase.LOBBY
        assert state.guild_id == "guild1"
        assert state.channel_id == "chan1"

    def test_game_id_is_unique(self, engine):
        s1 = engine.create_game("guild1", "chan1")
        s2 = engine.create_game("guild2", "chan2")
        assert s1.game_id != s2.game_id

    def test_new_game_has_no_players(self, engine):
        state = engine.create_game("g", "c")
        assert state.players == {}

    def test_version_starts_at_zero(self, engine):
        state = engine.create_game("g", "c")
        assert state.version == 0


# ---------------------------------------------------------------------------
# join
# ---------------------------------------------------------------------------


class TestJoin:
    def test_adds_player_to_lobby(self, engine):
        state = engine.create_game("g", "c")
        state2 = engine.join(state.game_id, "u1", "Alice")
        assert "u1" in state2.players
        assert state2.players["u1"].display_name == "Alice"

    def test_multiple_players_can_join(self, engine):
        state = engine.create_game("g", "c")
        engine.join(state.game_id, "u1", "Alice")
        state3 = engine.join(state.game_id, "u2", "Bob")
        assert len(state3.players) == 2

    def test_join_nonexistent_game_raises(self, engine):
        with pytest.raises(GameNotFoundError):
            engine.join("no-such-id", "u1", "Alice")

    def test_join_raises_if_not_lobby(self, engine):
        state = engine.create_game("g", "c")
        _add_players(engine, state.game_id, 3)
        engine.start(state.game_id)
        with pytest.raises(InvalidPhaseError):
            engine.join(state.game_id, "u99", "Late")

    def test_join_duplicate_player_is_idempotent(self, engine):
        state = engine.create_game("g", "c")
        engine.join(state.game_id, "u1", "Alice")
        state2 = engine.join(state.game_id, "u1", "Alice")
        assert len(state2.players) == 1

    def test_version_increments_on_join(self, engine):
        state = engine.create_game("g", "c")
        v0 = state.version
        state2 = engine.join(state.game_id, "u1", "Alice")
        assert state2.version == v0 + 1


# ---------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------


class TestStart:
    def test_transitions_lobby_to_first_night(self, engine):
        state = engine.create_game("g", "c")
        _add_players(engine, state.game_id, 3)
        state2 = engine.start(state.game_id)
        assert state2.phase == Phase.FIRST_NIGHT

    def test_assigns_roles_to_all_players(self, engine):
        state = engine.create_game("g", "c")
        _add_players(engine, state.game_id, 4)
        state2 = engine.start(state.game_id)
        for p in state2.players.values():
            assert p.role is not None

    def test_start_requires_minimum_three_players(self, engine):
        state = engine.create_game("g", "c")
        _add_players(engine, state.game_id, 2)
        with pytest.raises(ActionNotAllowedError):
            engine.start(state.game_id)

    def test_start_nonexistent_game_raises(self, engine):
        with pytest.raises(GameNotFoundError):
            engine.start("no-such-id")

    def test_start_non_lobby_raises(self, engine):
        state = engine.create_game("g", "c")
        _add_players(engine, state.game_id, 3)
        engine.start(state.game_id)
        with pytest.raises(InvalidPhaseError):
            engine.start(state.game_id)

    def test_classic_three_player_role_counts(self, engine):
        state = engine.create_game("g", "c")
        _add_players(engine, state.game_id, 3)
        state2 = engine.start(state.game_id)
        roles = [p.role for p in state2.players.values()]
        assert roles.count("werewolf") == 1
        assert roles.count("seer") == 1
        assert roles.count("villager") == 1

    def test_classic_five_player_role_counts(self, engine):
        state = engine.create_game("g", "c")
        _add_players(engine, state.game_id, 5)
        state2 = engine.start(state.game_id)
        roles = [p.role for p in state2.players.values()]
        assert roles.count("werewolf") == 2
        assert roles.count("seer") == 1

    def test_started_at_set_on_start(self, engine):
        state = engine.create_game("g", "c")
        _add_players(engine, state.game_id, 3)
        state2 = engine.start(state.game_id)
        assert state2.started_at is not None


# ---------------------------------------------------------------------------
# vote
# ---------------------------------------------------------------------------


class TestVote:
    def _start_game(self, engine, n=3):
        state = engine.create_game("g", "c")
        _add_players(engine, state.game_id, n)
        return engine.start(state.game_id)

    def _advance_to_day(self, engine, state):
        """Resolve first night to get to DAY phase."""
        return engine.resolve_phase(state.game_id)

    def test_vote_requires_day_phase(self, engine):
        state = self._start_game(engine)
        assert state.phase == Phase.FIRST_NIGHT
        with pytest.raises(InvalidPhaseError):
            engine.vote(state.game_id, "u0", "u1")

    def test_vote_records_vote(self, engine):
        state = self._start_game(engine)
        day = self._advance_to_day(engine, state)
        assert day.phase == Phase.DAY
        player_ids = list(day.players.keys())
        state2 = engine.vote(day.game_id, player_ids[0], player_ids[1])
        assert state2.day_votes[player_ids[0]] == player_ids[1]

    def test_vote_noone_records_none_target(self, engine):
        state = self._start_game(engine)
        day = self._advance_to_day(engine, state)
        player_ids = list(day.players.keys())
        state2 = engine.vote(day.game_id, player_ids[0], None)
        assert state2.day_votes[player_ids[0]] is None

    def test_vote_nonexistent_game_raises(self, engine):
        with pytest.raises(GameNotFoundError):
            engine.vote("no-such-id", "u0", "u1")

    def test_vote_dead_player_raises(self, engine):
        state = self._start_game(engine, n=5)
        day = self._advance_to_day(engine, state)
        player_ids = list(day.players.keys())
        day.players[player_ids[0]].alive = False
        engine._repo.save_game(day)
        with pytest.raises(ActionNotAllowedError):
            engine.vote(day.game_id, player_ids[0], player_ids[1])


# ---------------------------------------------------------------------------
# submit_night_action
# ---------------------------------------------------------------------------


class TestSubmitNightAction:
    def _start_at_night(self, engine, n=4):
        state = engine.create_game("g", "c")
        _add_players(engine, state.game_id, n)
        started = engine.start(state.game_id)
        # FIRST_NIGHT: resolve to advance to DAY then to NIGHT
        day = engine.resolve_phase(started.game_id)
        night = engine.resolve_phase(day.game_id)
        return night

    def test_submit_action_wrong_phase_raises(self, engine):
        state = engine.create_game("g", "c")
        _add_players(engine, state.game_id, 3)
        started = engine.start(state.game_id)
        assert started.phase == Phase.FIRST_NIGHT
        wolf_id = next(
            p.user_id for p in started.players.values() if p.role == "werewolf"
        )
        action = Action(actor_id=wolf_id, action_type="kill", target_id="u1")
        with pytest.raises(InvalidPhaseError):
            engine.submit_night_action(started.game_id, wolf_id, action)

    def test_submit_nonexistent_game_raises(self, engine):
        action = Action(actor_id="u0", action_type="kill", target_id="u1")
        with pytest.raises(GameNotFoundError):
            engine.submit_night_action("no-such-id", "u0", action)

    def test_submit_records_action(self, engine):
        # Use NIGHT: wolf action pending, so seer alone won't auto-resolve.
        state = engine.create_game("g", "c")
        _add_players(engine, state.game_id, 3)
        started = engine.start(state.game_id)
        day = engine.resolve_phase(started.game_id)  # FIRST_NIGHT -> DAY
        pids = list(day.players.keys())
        for pid in pids:
            engine.vote(day.game_id, pid, None)
        night = engine.resolve_phase(day.game_id)  # all noone -> NIGHT
        assert night.phase == Phase.NIGHT
        seer_id = next(p.user_id for p in night.players.values() if p.role == "seer")
        non_seer = next(p.user_id for p in night.players.values() if p.role != "seer")
        action = Action(actor_id=seer_id, action_type="investigate", target_id=non_seer)
        state2 = engine.submit_night_action(night.game_id, seer_id, action)
        # Wolves haven't voted yet -> no auto-resolve -> action still in pending
        assert seer_id in state2.pending_actions


# ---------------------------------------------------------------------------
# resolve_phase
# ---------------------------------------------------------------------------


class TestResolvePhase:
    def test_first_night_resolves_to_day(self, engine):
        state = engine.create_game("g", "c")
        _add_players(engine, state.game_id, 3)
        started = engine.start(state.game_id)
        assert started.phase == Phase.FIRST_NIGHT
        day = engine.resolve_phase(started.game_id)
        assert day.phase == Phase.DAY

    def test_resolve_is_idempotent_in_day(self, engine):
        state = engine.create_game("g", "c")
        _add_players(engine, state.game_id, 3)
        started = engine.start(state.game_id)
        day = engine.resolve_phase(started.game_id)
        assert day.phase == Phase.DAY
        day2 = engine.resolve_phase(day.game_id)
        assert day2.phase == Phase.DAY

    def test_resolve_nonexistent_game_raises(self, engine):
        with pytest.raises(GameNotFoundError):
            engine.resolve_phase("no-such-id")

    def test_day_resolves_to_night_after_all_votes(self, engine):
        state = engine.create_game("g", "c")
        _add_players(engine, state.game_id, 3)
        started = engine.start(state.game_id)
        day = engine.resolve_phase(started.game_id)
        player_ids = list(day.players.keys())
        # All players vote noone -> no lynch -> transitions to NIGHT
        for pid in player_ids:
            engine.vote(day.game_id, pid, None)
        night = engine.resolve_phase(day.game_id)
        assert night.phase == Phase.NIGHT

    def test_majority_vote_lynches_player(self, engine):
        state = engine.create_game("g", "c")
        _add_players(engine, state.game_id, 3)
        started = engine.start(state.game_id)
        day = engine.resolve_phase(started.game_id)
        player_ids = list(day.players.keys())
        target = player_ids[0]
        # Two out of three vote for same target -> majority
        engine.vote(day.game_id, player_ids[1], target)
        engine.vote(day.game_id, player_ids[2], target)
        night = engine.resolve_phase(day.game_id)
        assert night.phase in (Phase.NIGHT, Phase.OVER)
        assert not night.players[target].alive

    def test_game_ends_when_wolves_outnumber_village(self, engine):
        state = engine.create_game("g", "c")
        _add_players(engine, state.game_id, 3)
        started = engine.start(state.game_id)
        non_wolves = [
            p.user_id for p in started.players.values() if p.role != "werewolf"
        ]
        day = engine.resolve_phase(started.game_id)
        # Lynch a non-wolf so wolves win (1 wolf, 1 villager left -> wolves >= good)
        target = non_wolves[0]
        for pid in [p for p in day.players if p != target]:
            engine.vote(day.game_id, pid, target)
        over = engine.resolve_phase(day.game_id)
        assert over.phase == Phase.OVER

    def test_game_ends_when_all_wolves_dead(self, engine):
        state = engine.create_game("g", "c")
        _add_players(engine, state.game_id, 3)
        started = engine.start(state.game_id)
        wolf_id = next(
            p.user_id for p in started.players.values() if p.role == "werewolf"
        )
        day = engine.resolve_phase(started.game_id)
        non_wolf_voters = [p for p in day.players if p != wolf_id]
        for pid in non_wolf_voters:
            engine.vote(day.game_id, pid, wolf_id)
        over = engine.resolve_phase(day.game_id)
        assert over.phase == Phase.OVER


# ---------------------------------------------------------------------------
# get_public_state
# ---------------------------------------------------------------------------


class TestGetPublicState:
    def test_returns_public_game_state(self, engine):
        state = engine.create_game("g", "c")
        pub = engine.get_public_state(state.game_id)
        assert isinstance(pub, PublicGameState)

    def test_public_state_has_phase_and_round(self, engine):
        state = engine.create_game("g", "c")
        pub = engine.get_public_state(state.game_id)
        assert pub.phase == Phase.LOBBY
        assert pub.round == 0

    def test_public_state_does_not_expose_roles_for_alive_players(self, engine):
        state = engine.create_game("g", "c")
        _add_players(engine, state.game_id, 3)
        started = engine.start(state.game_id)
        pub = engine.get_public_state(started.game_id)
        for p in pub.players:
            if p["alive"]:
                assert p.get("role") is None

    def test_nonexistent_game_raises(self, engine):
        with pytest.raises(GameNotFoundError):
            engine.get_public_state("no-such-id")


# ---------------------------------------------------------------------------
# get_private_state
# ---------------------------------------------------------------------------


class TestGetPrivateState:
    def test_returns_private_player_state(self, engine):
        state = engine.create_game("g", "c")
        _add_players(engine, state.game_id, 3)
        started = engine.start(state.game_id)
        player_id = list(started.players.keys())[0]
        priv = engine.get_private_state(started.game_id, player_id)
        assert isinstance(priv, PrivatePlayerState)

    def test_private_state_exposes_own_role(self, engine):
        state = engine.create_game("g", "c")
        _add_players(engine, state.game_id, 3)
        started = engine.start(state.game_id)
        player_id = list(started.players.keys())[0]
        priv = engine.get_private_state(started.game_id, player_id)
        expected_role = started.players[player_id].role
        assert priv.role == expected_role

    def test_private_state_nonexistent_game_raises(self, engine):
        with pytest.raises(GameNotFoundError):
            engine.get_private_state("no-such-id", "u1")

    def test_private_state_nonexistent_player_raises(self, engine):
        state = engine.create_game("g", "c")
        with pytest.raises(ActionNotAllowedError):
            engine.get_private_state(state.game_id, "u-not-in-game")
