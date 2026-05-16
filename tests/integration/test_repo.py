"""Integration tests for DuckDBGameRepository."""

from __future__ import annotations

import duckdb
import pytest

from werewolf.core.models import Action, GameState, Phase, Player
from werewolf.infra.repo import ConcurrentModificationError, DuckDBGameRepository


@pytest.fixture
def conn():
    return duckdb.connect(":memory:")


@pytest.fixture
def repo(conn):
    return DuckDBGameRepository(conn)


def _game(
    game_id: str = "g1",
    guild_id: str = "guild1",
    channel_id: str = "ch1",
    phase: Phase = Phase.LOBBY,
    version: int = 0,
) -> GameState:
    return GameState(
        game_id=game_id,
        guild_id=guild_id,
        channel_id=channel_id,
        phase=phase,
        version=version,
    )


# ---------------------------------------------------------------------------
# Basic CRUD
# ---------------------------------------------------------------------------


def test_save_and_get_game(repo):
    game = _game()
    repo.save_game(game)
    result = repo.get_game("g1")
    assert result is not None
    assert result.game_id == "g1"
    assert result.guild_id == "guild1"
    assert result.phase == Phase.LOBBY


def test_get_game_not_found(repo):
    assert repo.get_game("missing") is None


def test_delete_game(repo):
    game = _game()
    repo.save_game(game)
    repo.delete_game("g1")
    assert repo.get_game("g1") is None


def test_delete_nonexistent_is_noop(repo):
    repo.delete_game("missing")  # should not raise


# ---------------------------------------------------------------------------
# get_active_game
# ---------------------------------------------------------------------------


def test_get_active_game_returns_non_over_game(repo):
    game = _game(phase=Phase.DAY)
    repo.save_game(game)
    result = repo.get_active_game("guild1")
    assert result is not None
    assert result.game_id == "g1"


def test_get_active_game_ignores_over(repo):
    game = _game(phase=Phase.OVER)
    repo.save_game(game)
    assert repo.get_active_game("guild1") is None


def test_get_active_game_not_found(repo):
    assert repo.get_active_game("no-such-guild") is None


def test_get_active_game_wrong_guild(repo):
    game = _game(guild_id="guild1", phase=Phase.DAY)
    repo.save_game(game)
    assert repo.get_active_game("guild2") is None


# ---------------------------------------------------------------------------
# get_game_by_player
# ---------------------------------------------------------------------------


def test_get_game_by_player(repo):
    game = _game(phase=Phase.DAY)
    game.players["u1"] = Player(user_id="u1", display_name="Alice")
    repo.save_game(game)
    result = repo.get_game_by_player("u1")
    assert result is not None
    assert result.game_id == "g1"


def test_get_game_by_player_not_found(repo):
    assert repo.get_game_by_player("nobody") is None


def test_get_game_by_player_ignores_over(repo):
    game = _game(phase=Phase.OVER)
    game.players["u1"] = Player(user_id="u1", display_name="Alice")
    repo.save_game(game)
    assert repo.get_game_by_player("u1") is None


# ---------------------------------------------------------------------------
# Round-trip fidelity
# ---------------------------------------------------------------------------


def test_players_round_trip(repo):
    game = _game()
    game.players["u1"] = Player(
        user_id="u1", display_name="Alice", role="werewolf", alive=False
    )
    game.players["u2"] = Player(user_id="u2", display_name="Bob", role="villager")
    repo.save_game(game)
    result = repo.get_game("g1")
    assert result is not None
    assert len(result.players) == 2
    alice = result.players["u1"]
    assert alice.display_name == "Alice"
    assert alice.role == "werewolf"
    assert alice.alive is False
    assert result.players["u2"].role == "villager"


def test_pending_actions_round_trip(repo):
    game = _game()
    game.pending_actions["u1"] = Action(
        actor_id="u1", action_type="kill", target_id="u2"
    )
    repo.save_game(game)
    result = repo.get_game("g1")
    assert result is not None
    assert "u1" in result.pending_actions
    act = result.pending_actions["u1"]
    assert act.action_type == "kill"
    assert act.target_id == "u2"


def test_day_votes_round_trip(repo):
    game = _game(phase=Phase.DAY)
    game.day_votes["u1"] = "u2"
    game.day_votes["u3"] = "u2"
    repo.save_game(game)
    result = repo.get_game("g1")
    assert result is not None
    assert result.day_votes == {"u1": "u2", "u3": "u2"}


def test_all_game_fields_round_trip(repo):
    game = _game(phase=Phase.NIGHT, version=3)
    game.round = 2
    game.night_kills_pending = True
    game.seer_checked = True
    game.bodyguard_protected = True
    game.hunter_shot_pending = True
    repo.save_game(game)
    result = repo.get_game("g1")
    assert result is not None
    assert result.phase == Phase.NIGHT
    assert result.round == 2
    assert result.version == 3
    assert result.night_kills_pending is True
    assert result.seer_checked is True
    assert result.bodyguard_protected is True
    assert result.hunter_shot_pending is True


# ---------------------------------------------------------------------------
# Optimistic concurrency
# ---------------------------------------------------------------------------


def test_save_new_game_succeeds(repo):
    game = _game(version=0)
    repo.save_game(game)
    assert repo.get_game("g1") is not None


def test_save_update_advances_version(repo):
    game = _game(version=0)
    repo.save_game(game)
    game.version = 1
    game.phase = Phase.FIRST_NIGHT
    repo.save_game(game)
    result = repo.get_game("g1")
    assert result.version == 1
    assert result.phase == Phase.FIRST_NIGHT


def test_concurrent_modification_raises(repo):
    game = _game(version=0)
    repo.save_game(game)

    # Simulate two writers loading version=0 and both trying to save version=1
    game_a = _game(version=1, phase=Phase.FIRST_NIGHT)
    game_b = _game(version=1, phase=Phase.DAY)

    repo.save_game(game_a)  # first writer succeeds (stored was 0, saving 1)

    with pytest.raises(ConcurrentModificationError):
        repo.save_game(game_b)  # second writer fails (stored is now 1, not 0)


def test_stale_version_raises(repo):
    game = _game(version=0)
    repo.save_game(game)
    game.version = 1
    repo.save_game(game)

    # Try to save an old version as if it were new
    stale = _game(version=1, phase=Phase.DAY)
    with pytest.raises(ConcurrentModificationError):
        repo.save_game(stale)


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_implements_game_repository_protocol(repo):
    from werewolf.core.protocols import GameRepository

    assert isinstance(repo, GameRepository)
