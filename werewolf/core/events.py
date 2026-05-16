from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from werewolf.core.models import Phase


class GameEvent(BaseModel):
    game_id: str
    event_type: str

    model_config = {"frozen": False}


class PlayerKilled(GameEvent):
    event_type: Literal["player_killed"] = "player_killed"
    player_id: str
    cause: str


class PhaseChanged(GameEvent):
    event_type: Literal["phase_changed"] = "phase_changed"
    old_phase: Phase
    new_phase: Phase
    round: int


class GameEnded(GameEvent):
    event_type: Literal["game_ended"] = "game_ended"
    winning_team: str
