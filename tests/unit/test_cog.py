"""Unit tests for WerewolfCog Discord commands."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from werewolf.core.engine import WerewolfEngine
from werewolf.core.models import GameState, Phase
from werewolf.discord.cog import WerewolfCog

# ---------------------------------------------------------------------------
# In-memory repository
# ---------------------------------------------------------------------------


class InMemoryRepo:
    def __init__(self) -> None:
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
            if user_id in g.players and g.phase != Phase.OVER:
                return g
        return None

    def save_game(self, game: GameState) -> None:
        self._games[game.game_id] = game

    def delete_game(self, game_id: str) -> None:
        self._games.pop(game_id, None)


# ---------------------------------------------------------------------------
# Context factories
# ---------------------------------------------------------------------------


def make_text_ctx(
    guild_id: str = "g1",
    channel_id: str = "c1",
    user_id: str = "u1",
    display_name: str = "Alice",
) -> AsyncMock:
    ctx = AsyncMock()
    ctx.send = AsyncMock()
    ctx.guild = MagicMock()
    ctx.guild.id = guild_id
    ctx.channel = MagicMock()
    ctx.channel.id = channel_id
    ctx.channel.__class__ = discord.TextChannel
    ctx.author = MagicMock()
    ctx.author.id = user_id
    ctx.author.display_name = display_name
    return ctx


def make_dm_ctx(
    user_id: str = "u1",
    display_name: str = "Alice",
) -> AsyncMock:
    ctx = AsyncMock()
    ctx.send = AsyncMock()
    ctx.guild = None
    ctx.channel = MagicMock()
    ctx.channel.__class__ = discord.DMChannel
    ctx.author = MagicMock()
    ctx.author.id = user_id
    ctx.author.display_name = display_name
    return ctx


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def repo() -> InMemoryRepo:
    return InMemoryRepo()


@pytest.fixture
def engine(repo: InMemoryRepo) -> WerewolfEngine:
    return WerewolfEngine(repo)


@pytest.fixture
def messaging() -> MagicMock:
    m = MagicMock()
    m.send_channel = AsyncMock()
    m.send_dm = AsyncMock()
    return m


@pytest.fixture
def cog(
    engine: WerewolfEngine, repo: InMemoryRepo, messaging: MagicMock
) -> WerewolfCog:
    return WerewolfCog(engine, repo, messaging)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _invoke(
    cog: WerewolfCog, command_name: str, ctx: AsyncMock, *args: object
) -> None:
    """Invoke a Cog command callback directly, bypassing the Command wrapper."""
    command = getattr(type(cog), command_name)
    await command.callback(cog, ctx, *args)


def _setup_started_game(
    engine: WerewolfEngine,
    repo: InMemoryRepo,
    roles: dict[str, str],
) -> str:
    """Create a game with forced roles in FIRST_NIGHT, return game_id."""
    game = engine.create_game("g1", "c1")
    for uid in roles:
        engine.join(game.game_id, uid, uid.capitalize())
    game = repo.get_game(game.game_id)
    assert game is not None
    game.phase = Phase.FIRST_NIGHT
    for uid, role in roles.items():
        game.players[uid].role = role
    repo.save_game(game)
    return game.game_id


# ---------------------------------------------------------------------------
# !new — channel command
# ---------------------------------------------------------------------------


async def test_new_creates_game_in_text_channel(
    cog: WerewolfCog, repo: InMemoryRepo
) -> None:
    ctx = make_text_ctx()
    await _invoke(cog, "new_game", ctx)
    ctx.send.assert_called_once()
    assert repo.get_active_game("g1") is not None


async def test_new_in_dm_is_noop(cog: WerewolfCog, repo: InMemoryRepo) -> None:
    ctx = make_dm_ctx()
    await _invoke(cog, "new_game", ctx)
    ctx.send.assert_not_called()
    assert repo.get_active_game("g1") is None


async def test_new_when_active_game_exists_sends_error(
    cog: WerewolfCog, engine: WerewolfEngine
) -> None:
    engine.create_game("g1", "c1")
    ctx = make_text_ctx()
    await _invoke(cog, "new_game", ctx)
    ctx.send.assert_called_once()
    sent = ctx.send.call_args[0][0]
    assert "already" in sent.lower()


# ---------------------------------------------------------------------------
# !join — channel command
# ---------------------------------------------------------------------------


async def test_join_adds_player_in_text_channel(
    cog: WerewolfCog, engine: WerewolfEngine, repo: InMemoryRepo
) -> None:
    engine.create_game("g1", "c1")
    ctx = make_text_ctx(user_id="u1", display_name="Alice")
    await _invoke(cog, "join_game", ctx)
    game = repo.get_active_game("g1")
    assert game is not None
    assert "u1" in game.players


async def test_join_in_dm_is_noop(cog: WerewolfCog, repo: InMemoryRepo) -> None:
    ctx = make_dm_ctx()
    await _invoke(cog, "join_game", ctx)
    ctx.send.assert_not_called()


async def test_join_no_active_game_sends_error(cog: WerewolfCog) -> None:
    ctx = make_text_ctx()
    await _invoke(cog, "join_game", ctx)
    ctx.send.assert_called_once()


# ---------------------------------------------------------------------------
# !leave — channel command
# ---------------------------------------------------------------------------


async def test_leave_removes_player(
    cog: WerewolfCog, engine: WerewolfEngine, repo: InMemoryRepo
) -> None:
    game = engine.create_game("g1", "c1")
    engine.join(game.game_id, "u1", "Alice")
    ctx = make_text_ctx(user_id="u1")
    await _invoke(cog, "leave_game", ctx)
    game = repo.get_active_game("g1")
    assert game is not None
    assert "u1" not in game.players


async def test_leave_in_dm_is_noop(cog: WerewolfCog) -> None:
    ctx = make_dm_ctx()
    await _invoke(cog, "leave_game", ctx)
    ctx.send.assert_not_called()


# ---------------------------------------------------------------------------
# !start — channel command
# ---------------------------------------------------------------------------


async def test_start_transitions_game_to_first_night(
    cog: WerewolfCog, engine: WerewolfEngine, repo: InMemoryRepo
) -> None:
    game = engine.create_game("g1", "c1")
    for i in range(3):
        engine.join(game.game_id, f"10{i}", f"Player{i}")
    ctx = make_text_ctx()
    await _invoke(cog, "start_game", ctx)
    game = repo.get_active_game("g1")
    assert game is not None
    assert game.phase == Phase.FIRST_NIGHT


async def test_start_sends_dm_with_role_to_each_player(
    cog: WerewolfCog, engine: WerewolfEngine, messaging: MagicMock
) -> None:
    game = engine.create_game("g1", "c1")
    for i in range(3):
        engine.join(game.game_id, f"10{i}", f"Player{i}")
    ctx = make_text_ctx()
    await _invoke(cog, "start_game", ctx)
    assert messaging.send_dm.call_count == 3


async def test_start_in_dm_is_noop(cog: WerewolfCog) -> None:
    ctx = make_dm_ctx()
    await _invoke(cog, "start_game", ctx)
    ctx.send.assert_not_called()


# ---------------------------------------------------------------------------
# !end — channel command
# ---------------------------------------------------------------------------


async def test_end_terminates_game(
    cog: WerewolfCog, engine: WerewolfEngine, repo: InMemoryRepo
) -> None:
    engine.create_game("g1", "c1")
    ctx = make_text_ctx()
    await _invoke(cog, "end_game", ctx)
    assert repo.get_active_game("g1") is None


async def test_end_in_dm_is_noop(cog: WerewolfCog) -> None:
    ctx = make_dm_ctx()
    await _invoke(cog, "end_game", ctx)
    ctx.send.assert_not_called()


# ---------------------------------------------------------------------------
# !status — channel command
# ---------------------------------------------------------------------------


async def test_status_sends_public_state(
    cog: WerewolfCog, engine: WerewolfEngine
) -> None:
    game = engine.create_game("g1", "c1")
    engine.join(game.game_id, "u1", "Alice")
    ctx = make_text_ctx()
    await _invoke(cog, "status", ctx)
    ctx.send.assert_called_once()


async def test_status_no_game_sends_error(cog: WerewolfCog) -> None:
    ctx = make_text_ctx()
    await _invoke(cog, "status", ctx)
    ctx.send.assert_called_once()


async def test_status_in_dm_is_noop(cog: WerewolfCog) -> None:
    ctx = make_dm_ctx()
    await _invoke(cog, "status", ctx)
    ctx.send.assert_not_called()


# ---------------------------------------------------------------------------
# !vote — channel command
# ---------------------------------------------------------------------------


async def test_vote_records_vote_in_text_channel(
    cog: WerewolfCog, engine: WerewolfEngine, repo: InMemoryRepo
) -> None:
    gid = _setup_started_game(
        engine, repo, {"u1": "werewolf", "u2": "seer", "u3": "villager"}
    )
    engine.resolve_phase(gid)  # FIRST_NIGHT -> DAY
    ctx = make_text_ctx(user_id="u1")
    await _invoke(cog, "vote", ctx, "u2")
    game = repo.get_game(gid)
    assert game is not None
    assert "u1" in game.day_votes


async def test_vote_in_dm_is_noop(cog: WerewolfCog) -> None:
    ctx = make_dm_ctx()
    await _invoke(cog, "vote", ctx, "u2")
    ctx.send.assert_not_called()


async def test_vote_wrong_phase_sends_error(
    cog: WerewolfCog, engine: WerewolfEngine, repo: InMemoryRepo
) -> None:
    _setup_started_game(
        engine, repo, {"u1": "werewolf", "u2": "seer", "u3": "villager"}
    )
    # Still in FIRST_NIGHT — voting not allowed
    ctx = make_text_ctx(user_id="u1")
    await _invoke(cog, "vote", ctx, "u2")
    ctx.send.assert_called_once()


# ---------------------------------------------------------------------------
# !see — DM command
# ---------------------------------------------------------------------------


async def test_see_submits_investigate_in_dm(
    cog: WerewolfCog, engine: WerewolfEngine, repo: InMemoryRepo
) -> None:
    gid = _setup_started_game(
        engine, repo, {"u1": "seer", "u2": "werewolf", "u3": "villager"}
    )
    ctx = make_dm_ctx(user_id="u1")
    await _invoke(cog, "see", ctx, "u2")
    ctx.send.assert_called_once()
    # Seer investigating on FIRST_NIGHT triggers auto-resolution; night advances to DAY
    game = repo.get_game(gid)
    assert game is not None
    assert game.phase == Phase.DAY


async def test_see_in_text_channel_is_noop(cog: WerewolfCog) -> None:
    ctx = make_text_ctx()
    await _invoke(cog, "see", ctx, "u2")
    ctx.send.assert_not_called()


async def test_see_result_is_included_in_response(
    cog: WerewolfCog, engine: WerewolfEngine, repo: InMemoryRepo
) -> None:
    _setup_started_game(
        engine, repo, {"u1": "seer", "u2": "werewolf", "u3": "villager"}
    )
    ctx = make_dm_ctx(user_id="u1")
    await _invoke(cog, "see", ctx, "u2")
    sent = ctx.send.call_args[0][0]
    assert "wolf" in sent.lower()


# ---------------------------------------------------------------------------
# !kill — DM command
# ---------------------------------------------------------------------------


async def test_kill_submits_kill_in_dm(
    cog: WerewolfCog, engine: WerewolfEngine, repo: InMemoryRepo
) -> None:
    gid = _setup_started_game(
        engine, repo, {"u1": "werewolf", "u2": "seer", "u3": "villager"}
    )
    engine.resolve_phase(gid)  # FIRST_NIGHT -> DAY
    game = repo.get_game(gid)
    assert game is not None
    game.phase = Phase.NIGHT
    repo.save_game(game)
    ctx = make_dm_ctx(user_id="u1")
    await _invoke(cog, "kill", ctx, "u3")
    ctx.send.assert_called_once()
    game = repo.get_game(gid)
    assert game is not None
    assert "u1" in game.pending_actions


async def test_kill_in_text_channel_is_noop(cog: WerewolfCog) -> None:
    ctx = make_text_ctx()
    await _invoke(cog, "kill", ctx, "u2")
    ctx.send.assert_not_called()


# ---------------------------------------------------------------------------
# !guard — DM command
# ---------------------------------------------------------------------------


async def test_guard_submits_protect_in_dm(
    cog: WerewolfCog, engine: WerewolfEngine, repo: InMemoryRepo
) -> None:
    gid = _setup_started_game(
        engine, repo, {"u1": "bodyguard", "u2": "werewolf", "u3": "villager"}
    )
    ctx = make_dm_ctx(user_id="u1")
    await _invoke(cog, "guard", ctx, "u3")
    ctx.send.assert_called_once()
    # Bodyguard on FIRST_NIGHT triggers auto-resolution; advances to DAY
    game = repo.get_game(gid)
    assert game is not None
    assert game.phase == Phase.DAY


async def test_guard_in_text_channel_is_noop(cog: WerewolfCog) -> None:
    ctx = make_text_ctx()
    await _invoke(cog, "guard", ctx, "u2")
    ctx.send.assert_not_called()


# ---------------------------------------------------------------------------
# !shoot — DM command
# ---------------------------------------------------------------------------


async def test_shoot_in_text_channel_is_noop(cog: WerewolfCog) -> None:
    ctx = make_text_ctx()
    await _invoke(cog, "shoot", ctx, "u2")
    ctx.send.assert_not_called()


async def test_shoot_sends_error_when_no_game(cog: WerewolfCog) -> None:
    ctx = make_dm_ctx(user_id="u1")
    await _invoke(cog, "shoot", ctx, "u2")
    ctx.send.assert_called_once()
