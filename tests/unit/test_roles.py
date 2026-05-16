"""Unit tests for Role base class, Villager, and Werewolf."""

from __future__ import annotations

import pytest

from werewolf.core.events import WolvesRevealed
from werewolf.core.models import GameState, Phase, Player
from werewolf.core.roles import Role, Villager, Werewolf


def _make_game(phase: Phase = Phase.FIRST_NIGHT, **extra) -> GameState:
    return GameState(
        game_id="g1",
        guild_id="guild1",
        channel_id="ch1",
        phase=phase,
        **extra,
    )


def _make_player(user_id: str, role: str = "villager", alive: bool = True) -> Player:
    return Player(user_id=user_id, display_name=user_id, role=role, alive=alive)


# ---------------------------------------------------------------------------
# Role base class contract
# ---------------------------------------------------------------------------


def test_role_is_abstract():
    with pytest.raises(TypeError):
        Role()  # type: ignore[abstract]


def test_role_has_name_attribute():
    assert hasattr(Villager, "name")
    assert hasattr(Werewolf, "name")


def test_villager_name():
    assert Villager.name == "villager"


def test_werewolf_name():
    assert Werewolf.name == "werewolf"


# ---------------------------------------------------------------------------
# Villager
# ---------------------------------------------------------------------------


class TestVillager:
    def setup_method(self):
        self.role = Villager()
        self.game = _make_game()
        self.player = _make_player("u1", "villager")

    def test_on_phase_start_returns_empty(self):
        for phase in Phase:
            game = _make_game(phase=phase)
            assert self.role.on_phase_start(game) == []

    def test_on_death_returns_empty(self):
        assert self.role.on_death(self.game, self.player) == []

    def test_validate_action_always_false(self):
        target = _make_player("u2")
        for phase in Phase:
            game = _make_game(phase=phase)
            assert self.role.validate_action(game, self.player, target) is False

    def test_validate_action_no_target_false(self):
        assert self.role.validate_action(self.game, self.player, None) is False


# ---------------------------------------------------------------------------
# Werewolf
# ---------------------------------------------------------------------------


class TestWerewolf:
    def setup_method(self):
        self.role = Werewolf()

    # -- on_phase_start --

    def test_first_night_reveals_wolves(self):
        wolf1 = _make_player("w1", "werewolf")
        wolf2 = _make_player("w2", "werewolf")
        villager = _make_player("v1", "villager")
        game = _make_game(
            phase=Phase.FIRST_NIGHT,
            players={"w1": wolf1, "w2": wolf2, "v1": villager},
        )
        events = self.role.on_phase_start(game)
        assert len(events) == 1
        evt = events[0]
        assert isinstance(evt, WolvesRevealed)
        assert set(evt.wolf_ids) == {"w1", "w2"}

    def test_first_night_single_wolf_reveals_self(self):
        wolf = _make_player("w1", "werewolf")
        villager = _make_player("v1", "villager")
        game = _make_game(
            phase=Phase.FIRST_NIGHT,
            players={"w1": wolf, "v1": villager},
        )
        events = self.role.on_phase_start(game)
        assert len(events) == 1
        assert events[0].wolf_ids == ["w1"]

    def test_non_first_night_returns_empty(self):
        wolf = _make_player("w1", "werewolf")
        game = _make_game(phase=Phase.NIGHT, players={"w1": wolf})
        assert self.role.on_phase_start(game) == []

    def test_day_phase_returns_empty(self):
        wolf = _make_player("w1", "werewolf")
        game = _make_game(phase=Phase.DAY, players={"w1": wolf})
        assert self.role.on_phase_start(game) == []

    def test_on_death_returns_empty(self):
        wolf = _make_player("w1", "werewolf")
        game = _make_game(players={"w1": wolf})
        assert self.role.on_death(game, wolf) == []

    # -- validate_action --

    def test_kill_valid_during_first_night(self):
        wolf = _make_player("w1", "werewolf")
        target = _make_player("v1", "villager")
        game = _make_game(
            phase=Phase.FIRST_NIGHT,
            players={"w1": wolf, "v1": target},
        )
        assert self.role.validate_action(game, wolf, target) is True

    def test_kill_valid_during_night(self):
        wolf = _make_player("w1", "werewolf")
        target = _make_player("v1", "villager")
        game = _make_game(
            phase=Phase.NIGHT,
            players={"w1": wolf, "v1": target},
        )
        assert self.role.validate_action(game, wolf, target) is True

    def test_kill_invalid_during_day(self):
        wolf = _make_player("w1", "werewolf")
        target = _make_player("v1", "villager")
        game = _make_game(
            phase=Phase.DAY,
            players={"w1": wolf, "v1": target},
        )
        assert self.role.validate_action(game, wolf, target) is False

    def test_kill_invalid_no_target(self):
        wolf = _make_player("w1", "werewolf")
        game = _make_game(phase=Phase.NIGHT, players={"w1": wolf})
        assert self.role.validate_action(game, wolf, None) is False

    def test_kill_invalid_dead_actor(self):
        wolf = _make_player("w1", "werewolf", alive=False)
        target = _make_player("v1", "villager")
        game = _make_game(
            phase=Phase.NIGHT,
            players={"w1": wolf, "v1": target},
        )
        assert self.role.validate_action(game, wolf, target) is False

    def test_kill_invalid_dead_target(self):
        wolf = _make_player("w1", "werewolf")
        target = _make_player("v1", "villager", alive=False)
        game = _make_game(
            phase=Phase.NIGHT,
            players={"w1": wolf, "v1": target},
        )
        assert self.role.validate_action(game, wolf, target) is False

    def test_kill_invalid_self_target(self):
        wolf = _make_player("w1", "werewolf")
        game = _make_game(phase=Phase.NIGHT, players={"w1": wolf})
        assert self.role.validate_action(game, wolf, wolf) is False

    def test_kill_invalid_lobby_phase(self):
        wolf = _make_player("w1", "werewolf")
        target = _make_player("v1", "villager")
        game = _make_game(
            phase=Phase.LOBBY,
            players={"w1": wolf, "v1": target},
        )
        assert self.role.validate_action(game, wolf, target) is False
