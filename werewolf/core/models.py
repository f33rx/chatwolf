from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class Phase(StrEnum):
    LOBBY = "LOBBY"
    FIRST_NIGHT = "FIRST_NIGHT"
    DAY = "DAY"
    NIGHT = "NIGHT"
    OVER = "OVER"


RoleStrategy = Literal["classic", "chaos", "vanilla"]


class Player(BaseModel):
    user_id: str
    display_name: str
    role: str | None = None
    alive: bool = True
    protected: bool = False

    model_config = {"frozen": False}


class Action(BaseModel):
    actor_id: str
    action_type: str
    target_id: str | None = None

    model_config = {"frozen": False}


class GameState(BaseModel):
    game_id: str
    guild_id: str
    channel_id: str
    phase: Phase = Phase.LOBBY
    round: int = 0
    version: Annotated[int, Field(ge=0)] = 0
    role_strategy: RoleStrategy = "classic"
    players: dict[str, Player] = Field(default_factory=dict)
    pending_actions: dict[str, Action] = Field(default_factory=dict)
    day_votes: dict[str, str] = Field(default_factory=dict)
    night_kills_pending: bool = False
    seer_checked: bool = False
    bodyguard_protected: bool = False
    hunter_shot_pending: bool = False
    winner: str | None = None
    last_guarded_user_id: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None

    model_config = {"frozen": False}
