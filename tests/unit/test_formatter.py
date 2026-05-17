"""Unit tests for werewolf/discord/formatter.py."""

from __future__ import annotations

import discord
import pytest

from werewolf.core.events import GameEnded, PhaseChanged, PlayerKilled
from werewolf.core.models import GameState, Phase, Player
from werewolf.discord.formatter import (
    Formatter,
    format_death,
    format_game_end,
    format_phase_announcement,
    format_role_reveal,
    format_status,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_player(
    uid: str, name: str, role: str = "villager", alive: bool = True
) -> Player:
    return Player(user_id=uid, display_name=name, role=role, alive=alive)


def make_game(**kwargs) -> GameState:
    defaults = dict(
        game_id="game-1",
        guild_id="guild-1",
        channel_id="ch-1",
        phase=Phase.DAY,
        round=1,
    )
    defaults.update(kwargs)
    return GameState(**defaults)


# ---------------------------------------------------------------------------
# format_role_reveal
# ---------------------------------------------------------------------------


def test_format_role_reveal_contains_player_name():
    player = make_player("1", "Alice", "villager")
    msg = format_role_reveal(player, "villager")
    assert "Alice" in msg


def test_format_role_reveal_contains_role():
    player = make_player("1", "Alice", "villager")
    msg = format_role_reveal(player, "villager")
    assert "villager" in msg.lower()


def test_format_role_reveal_werewolf():
    player = make_player("2", "Bob", "werewolf")
    msg = format_role_reveal(player, "werewolf")
    assert "werewolf" in msg.lower()


def test_format_role_reveal_seer():
    player = make_player("3", "Carol", "seer")
    msg = format_role_reveal(player, "seer")
    assert "seer" in msg.lower()


def test_format_role_reveal_returns_str():
    player = make_player("1", "Alice")
    result = format_role_reveal(player, "villager")
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# format_death
# ---------------------------------------------------------------------------


def test_format_death_contains_player_name():
    player = make_player("1", "Alice")
    msg = format_death(player, "lynched")
    assert "Alice" in msg


def test_format_death_contains_cause_lynched():
    player = make_player("1", "Alice")
    msg = format_death(player, "lynched")
    assert "lynch" in msg.lower()


def test_format_death_contains_cause_wolf():
    player = make_player("2", "Bob")
    msg = format_death(player, "wolf")
    assert "wolf" in msg.lower()


def test_format_death_reveals_role():
    player = make_player("1", "Alice", "seer")
    msg = format_death(player, "lynched")
    assert "seer" in msg.lower()


def test_format_death_returns_str():
    player = make_player("1", "Alice")
    result = format_death(player, "lynched")
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# format_phase_announcement
# ---------------------------------------------------------------------------


def test_format_phase_announcement_returns_embed():
    game = make_game()
    result = format_phase_announcement(Phase.DAY, game)
    assert isinstance(result, discord.Embed)


def test_format_phase_announcement_day_has_title():
    game = make_game(phase=Phase.DAY)
    embed = format_phase_announcement(Phase.DAY, game)
    assert embed.title is not None
    assert embed.title != ""


def test_format_phase_announcement_night_has_title():
    game = make_game(phase=Phase.NIGHT)
    embed = format_phase_announcement(Phase.NIGHT, game)
    assert embed.title is not None
    assert "night" in embed.title.lower()


def test_format_phase_announcement_day_mentions_day():
    game = make_game(phase=Phase.DAY)
    embed = format_phase_announcement(Phase.DAY, game)
    assert "day" in embed.title.lower() or (
        embed.description and "day" in embed.description.lower()
    )


def test_format_phase_announcement_includes_round():
    game = make_game(round=3)
    embed = format_phase_announcement(Phase.DAY, game)
    assert "3" in (embed.title or "") or "3" in (embed.description or "")


def test_format_phase_announcement_lists_alive_players():
    game = make_game()
    game.players = {
        "1": make_player("1", "Alice"),
        "2": make_player("2", "Bob", alive=False),
    }
    embed = format_phase_announcement(Phase.DAY, game)
    combined = " ".join(f.value for f in embed.fields if f.value) + (
        embed.description or ""
    )
    assert "Alice" in combined


# ---------------------------------------------------------------------------
# format_game_end
# ---------------------------------------------------------------------------


def test_format_game_end_returns_embed():
    players = [make_player("1", "Alice", "villager")]
    result = format_game_end("villager", players)
    assert isinstance(result, discord.Embed)


def test_format_game_end_village_win():
    players = [make_player("1", "Alice", "villager")]
    embed = format_game_end("villager", players)
    text = (embed.title or "") + (embed.description or "")
    assert "village" in text.lower() or "villager" in text.lower()


def test_format_game_end_werewolf_win():
    players = [make_player("1", "Alice", "werewolf")]
    embed = format_game_end("werewolf", players)
    text = (embed.title or "") + (embed.description or "")
    assert "werewolf" in text.lower()


def test_format_game_end_tanner_win():
    players = [make_player("1", "Alice", "tanner")]
    embed = format_game_end("tanner", players)
    text = (embed.title or "") + (embed.description or "")
    assert "tanner" in text.lower()


def test_format_game_end_lists_players():
    players = [
        make_player("1", "Alice", "villager"),
        make_player("2", "Bob", "werewolf"),
    ]
    embed = format_game_end("villager", players)
    combined = (embed.description or "") + " ".join(
        f.value for f in embed.fields if f.value
    )
    assert "Alice" in combined or "Bob" in combined


# ---------------------------------------------------------------------------
# format_status
# ---------------------------------------------------------------------------


def test_format_status_returns_embed():
    game = make_game()
    result = format_status(game)
    assert isinstance(result, discord.Embed)


def test_format_status_shows_phase():
    game = make_game(phase=Phase.DAY)
    embed = format_status(game)
    combined = (
        (embed.title or "")
        + (embed.description or "")
        + " ".join(f.value for f in embed.fields if f.value)
    )
    assert "day" in combined.lower()


def test_format_status_shows_players():
    game = make_game()
    game.players = {
        "1": make_player("1", "Alice"),
        "2": make_player("2", "Bob", alive=False),
    }
    embed = format_status(game)
    combined = (embed.description or "") + " ".join(
        f.value for f in embed.fields if f.value
    )
    assert "Alice" in combined
    assert "Bob" in combined


def test_format_status_shows_alive_count():
    game = make_game()
    game.players = {
        "1": make_player("1", "Alice"),
        "2": make_player("2", "Bob", alive=False),
    }
    embed = format_status(game)
    combined = (embed.description or "") + " ".join(
        f.value for f in embed.fields if f.value
    )
    assert "1" in combined


# ---------------------------------------------------------------------------
# Formatter class (dispatch via MessagingProtocol)
# ---------------------------------------------------------------------------


class FakeMessaging:
    def __init__(self):
        self.channel_calls: list[tuple] = []
        self.dm_calls: list[tuple] = []

    async def send_channel(self, channel_id: int, message) -> None:
        self.channel_calls.append((channel_id, message))

    async def send_dm(self, user_id: int, message) -> None:
        self.dm_calls.append((user_id, message))


@pytest.mark.asyncio
async def test_formatter_send_channel_player_killed():
    game = make_game()
    game.players["1"] = make_player("1", "Alice", "seer")
    messaging = FakeMessaging()
    formatter = Formatter(messaging)

    event = PlayerKilled(game_id="game-1", player_id="1", cause="lynched")
    await formatter.send_channel(42, event, game=game)

    assert len(messaging.channel_calls) == 1
    channel_id, msg = messaging.channel_calls[0]
    assert channel_id == 42
    assert "Alice" in str(msg)


@pytest.mark.asyncio
async def test_formatter_send_channel_phase_changed():
    game = make_game(phase=Phase.NIGHT)
    messaging = FakeMessaging()
    formatter = Formatter(messaging)

    event = PhaseChanged(
        game_id="game-1", old_phase=Phase.DAY, new_phase=Phase.NIGHT, round=1
    )
    await formatter.send_channel(42, event, game=game)

    assert len(messaging.channel_calls) == 1
    _, msg = messaging.channel_calls[0]
    assert isinstance(msg, discord.Embed)


@pytest.mark.asyncio
async def test_formatter_send_channel_game_ended():
    game = make_game(phase=Phase.OVER)
    game.players["1"] = make_player("1", "Alice", "villager")
    messaging = FakeMessaging()
    formatter = Formatter(messaging)

    event = GameEnded(game_id="game-1", winning_team="villager")
    await formatter.send_channel(42, event, game=game)

    assert len(messaging.channel_calls) == 1
    _, msg = messaging.channel_calls[0]
    assert isinstance(msg, discord.Embed)


@pytest.mark.asyncio
async def test_formatter_send_dm_role_reveal():
    game = make_game()
    game.players["99"] = make_player("99", "Dave", "seer")
    messaging = FakeMessaging()
    formatter = Formatter(messaging)

    await formatter.send_dm(99, game.players["99"])

    assert len(messaging.dm_calls) == 1
    user_id, msg = messaging.dm_calls[0]
    assert user_id == 99
    assert "seer" in str(msg).lower()
