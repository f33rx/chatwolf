"""Discord embed and message formatting for Werewolf game events.

All embed construction lives here. Nothing in cog.py creates embeds directly.
"""

from __future__ import annotations

from typing import Any

import discord

from werewolf.core.engine import PublicGameState
from werewolf.core.events import GameEnded, GameEvent, PhaseChanged, PlayerKilled
from werewolf.core.models import GameState, Phase, Player
from werewolf.core.protocols import MessagingProtocol

# ---------------------------------------------------------------------------
# Color palette
# ---------------------------------------------------------------------------

_COLOR_DAY = discord.Color.gold()
_COLOR_NIGHT = discord.Color.dark_blue()
_COLOR_VILLAGE_WIN = discord.Color.green()
_COLOR_WOLF_WIN = discord.Color.dark_red()
_COLOR_TANNER_WIN = discord.Color.purple()
_COLOR_STATUS = discord.Color.blurple()

# ---------------------------------------------------------------------------
# Pure format functions
# ---------------------------------------------------------------------------

_ROLE_INTROS: dict[str, str] = {
    "villager": "You are a **Villager**. Find and lynch the werewolves!",
    "werewolf": "You are a **Werewolf**. Hunt the villagers each night!",
    "seer": "You are the **Seer**. Each night you may investigate one player.",
    "hunter": "You are the **Hunter**. If you die, you may shoot one player.",
    "bodyguard": (
        "You are the **Bodyguard**. Each night protect one player from the wolf."
    ),
    "tanner": (
        "You are the **Tanner**. You win only if you are lynched by the village."
    ),
}


def format_role_reveal(player: Player, role: str) -> str:
    """Return a DM string revealing a player's role assignment."""
    line = _ROLE_INTROS.get(role, f"You are a **{role.title()}**.")
    return f"Hello, {player.display_name}! {line}"


def format_death(player: Player, cause: str) -> str:
    """Return a channel string announcing a player death."""
    role_tag = f" They were the **{player.role.title()}**." if player.role else ""
    name = player.display_name
    if cause == "lynched":
        return f"The village has spoken. **{name}** has been lynched!{role_tag}"
    if cause == "wolf":
        return f"A wolf struck in the night! **{name}** was killed!{role_tag}"
    return f"**{name}** has died ({cause}).{role_tag}"


def format_phase_announcement(phase: Phase, game: GameState) -> discord.Embed:
    """Return a Discord Embed announcing a phase transition."""
    alive = [p for p in game.players.values() if p.alive]
    alive_names = ", ".join(p.display_name for p in alive) if alive else "none"

    if phase == Phase.DAY:
        embed = discord.Embed(
            title=f"Day {game.round} — The village awakens",
            description=(
                "Discuss and decide who to lynch. "
                "Use `!vote @player` or `!vote noone`.\n\n"
                f"**Alive ({len(alive)}):** {alive_names}"
            ),
            color=_COLOR_DAY,
        )
    elif phase == Phase.NIGHT:
        embed = discord.Embed(
            title=f"Night {game.round} — Darkness falls",
            description=(
                "The village sleeps. Special roles: check your DMs.\n\n"
                f"**Alive ({len(alive)}):** {alive_names}"
            ),
            color=_COLOR_NIGHT,
        )
    elif phase == Phase.FIRST_NIGHT:
        embed = discord.Embed(
            title="Night falls for the first time",
            description=(
                "Roles have been assigned. Check your DMs!\n\n"
                f"**Players ({len(alive)}):** {alive_names}"
            ),
            color=_COLOR_NIGHT,
        )
    else:
        embed = discord.Embed(
            title=f"Phase: {phase}",
            description=f"Round {game.round}",
            color=_COLOR_STATUS,
        )

    return embed


_GAME_END_TITLES = {
    "villager": "The village wins!",
    "werewolf": "The werewolf pack wins!",
    "tanner": "The Tanner wins!",
}
_GAME_END_COLORS = {
    "villager": _COLOR_VILLAGE_WIN,
    "werewolf": _COLOR_WOLF_WIN,
    "tanner": _COLOR_TANNER_WIN,
}
_GAME_END_DESCRIPTIONS = {
    "villager": "All werewolves eliminated. Peace returns to the village.",
    "werewolf": "The werewolf pack now outnumbers the village. All hope is lost.",
    "tanner": "The Tanner was lynched and claims a twisted victory.",
}


def format_game_end(winner: str, players: list[Player]) -> discord.Embed:
    """Return a Discord Embed announcing the game result."""
    title = _GAME_END_TITLES.get(winner, f"{winner.title()} wins!")
    color = _GAME_END_COLORS.get(winner, _COLOR_STATUS)
    description = _GAME_END_DESCRIPTIONS.get(winner, "")

    embed = discord.Embed(title=title, description=description, color=color)

    if players:
        lines = [f"{p.display_name} — {p.role or 'unknown'}" for p in players]
        embed.add_field(name="Final roles", value="\n".join(lines), inline=False)

    return embed


def format_status(game: GameState) -> discord.Embed:
    """Return a Discord Embed showing current game status."""
    alive = [p for p in game.players.values() if p.alive]
    dead = [p for p in game.players.values() if not p.alive]

    embed = discord.Embed(
        title="Werewolf — Game Status",
        description=f"**Phase:** {game.phase}  |  **Round:** {game.round}",
        color=_COLOR_STATUS,
    )

    if alive:
        embed.add_field(
            name=f"Alive ({len(alive)})",
            value="\n".join(p.display_name for p in alive),
            inline=True,
        )
    if dead:
        dead_lines = [f"~~{p.display_name}~~ ({p.role or '?'})" for p in dead]
        embed.add_field(
            name=f"Dead ({len(dead)})",
            value="\n".join(dead_lines),
            inline=True,
        )

    return embed


# ---------------------------------------------------------------------------
# Cog command response strings (used by WerewolfCog for command replies)
# ---------------------------------------------------------------------------


def game_created() -> str:
    return "Werewolf game created! Type !join to join."


def game_already_active() -> str:
    return "A game is already active in this channel."


def no_active_game() -> str:
    return "No active game in this channel. Use !new to start one."


def player_joined(display_name: str, player_count: int) -> str:
    return f"{display_name} joined ({player_count} player(s) in lobby)."


def player_left(display_name: str) -> str:
    return f"{display_name} left the game."


def wrong_phase(msg: str = "") -> str:
    return msg if msg else "That action is not allowed in the current phase."


def game_started(player_count: int) -> str:
    return (
        f"The game has started with {player_count} players! "
        "Check your DMs for your role."
    )


def role_assigned(role: str) -> str:
    return f"Your role is: **{role}**."


def public_state(state: PublicGameState) -> str:
    alive = [p for p in state.players if p["alive"]]
    dead = [p for p in state.players if not p["alive"]]
    lines = [f"Phase: {state.phase.value} | Round: {state.round}"]
    lines.append(
        f"Alive ({len(alive)}): "
        + (", ".join(p["display_name"] for p in alive) or "none")
    )
    if dead:
        lines.append(
            "Dead: "
            + ", ".join(f"{p['display_name']} ({p.get('role', '?')})" for p in dead)
        )
    return "\n".join(lines)


def vote_recorded(voter_name: str) -> str:
    return f"Vote recorded from {voter_name}."


def action_submitted() -> str:
    return "Your action has been submitted."


def game_ended() -> str:
    return "The game has been ended."


def investigation_result(target_name: str, result: str) -> str:
    return f"{target_name} is a **{result}**."


# ---------------------------------------------------------------------------
# Formatter class -- dispatches GameEvents via MessagingProtocol
# ---------------------------------------------------------------------------


class Formatter:
    """Routes GameEvents to formatted messages and sends via MessagingProtocol."""

    def __init__(self, messaging: MessagingProtocol) -> None:
        self._m = messaging

    async def send_channel(
        self, channel_id: int, event: GameEvent, *, game: GameState
    ) -> None:
        """Format event and send to the given channel."""
        payload: Any

        if isinstance(event, PlayerKilled):
            player = game.players.get(event.player_id)
            if player is None:
                return
            payload = format_death(player, event.cause)
            await self._m.send_channel(channel_id, payload)

        elif isinstance(event, PhaseChanged):
            payload = format_phase_announcement(event.new_phase, game)
            await self._m.send_channel(channel_id, payload)

        elif isinstance(event, GameEnded):
            players = list(game.players.values())
            payload = format_game_end(event.winning_team, players)
            await self._m.send_channel(channel_id, payload)

    async def send_dm(self, user_id: int, player: Player) -> None:
        """Send a role-reveal DM to the given user."""
        role = player.role or "unknown"
        msg = format_role_reveal(player, role)
        await self._m.send_dm(user_id, msg)
