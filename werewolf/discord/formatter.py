"""Format game state and events as strings for Discord output."""

from __future__ import annotations

from werewolf.core.engine import PublicGameState


def game_created() -> str:
    return "Werewolf game created! Type !join to join."


def game_already_active() -> str:
    return "A game is already active in this channel."


def no_active_game() -> str:
    return "No active game in this channel. Use !new to start one."


def player_joined(display_name: str, player_count: int) -> str:
    return f"{display_name} joined ({player_count} player(s) in lobby)."


def player_already_joined() -> str:
    return "You are already in this game."


def player_left(display_name: str) -> str:
    return f"{display_name} left the game."


def wrong_phase(msg: str = "") -> str:
    return msg if msg else "That action is not allowed in the current phase."


def not_enough_players() -> str:
    return "Need at least 3 players to start."


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
