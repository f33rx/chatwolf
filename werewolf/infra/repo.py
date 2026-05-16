"""DuckDB implementation of GameRepository."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import duckdb

from werewolf.core.models import Action, GameState, Phase, Player

if TYPE_CHECKING:
    pass

_DDL = """
CREATE TABLE IF NOT EXISTS games (
    game_id       VARCHAR PRIMARY KEY,
    guild_id      VARCHAR NOT NULL,
    channel_id    VARCHAR NOT NULL,
    phase         VARCHAR NOT NULL,
    round         INTEGER NOT NULL,
    version       INTEGER NOT NULL,
    role_strategy VARCHAR NOT NULL,
    day_votes     JSON    NOT NULL,
    night_kills_pending   BOOLEAN NOT NULL,
    seer_checked          BOOLEAN NOT NULL,
    bodyguard_protected   BOOLEAN NOT NULL,
    hunter_shot_pending   BOOLEAN NOT NULL,
    started_at    TIMESTAMPTZ,
    ended_at      TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS players (
    game_id      VARCHAR NOT NULL,
    user_id      VARCHAR NOT NULL,
    display_name VARCHAR NOT NULL,
    role         VARCHAR,
    alive        BOOLEAN NOT NULL,
    protected    BOOLEAN NOT NULL,
    PRIMARY KEY (game_id, user_id)
);

CREATE TABLE IF NOT EXISTS actions (
    game_id     VARCHAR NOT NULL,
    actor_id    VARCHAR NOT NULL,
    action_type VARCHAR NOT NULL,
    target_id   VARCHAR,
    PRIMARY KEY (game_id, actor_id)
);

CREATE TABLE IF NOT EXISTS event_log (
    id          INTEGER PRIMARY KEY,
    game_id     VARCHAR NOT NULL,
    event_type  VARCHAR NOT NULL,
    payload     JSON    NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


class ConcurrentModificationError(Exception):
    pass


class DuckDBGameRepository:
    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        self._conn = conn
        self._conn.execute(_DDL)

    # ------------------------------------------------------------------
    # Protocol methods
    # ------------------------------------------------------------------

    def get_game(self, game_id: str) -> GameState | None:
        row = self._conn.execute(
            "SELECT * FROM games WHERE game_id = ?", [game_id]
        ).fetchone()
        if row is None:
            return None
        return self._hydrate(row)

    def get_active_game(self, guild_id: str) -> GameState | None:
        row = self._conn.execute(
            "SELECT * FROM games WHERE guild_id = ? AND phase != 'OVER' LIMIT 1",
            [guild_id],
        ).fetchone()
        if row is None:
            return None
        return self._hydrate(row)

    def get_game_by_player(self, user_id: str) -> GameState | None:
        row = self._conn.execute(
            """
            SELECT g.* FROM games g
            JOIN players p ON g.game_id = p.game_id
            WHERE p.user_id = ? AND g.phase != 'OVER'
            LIMIT 1
            """,
            [user_id],
        ).fetchone()
        if row is None:
            return None
        return self._hydrate(row)

    def save_game(self, game: GameState) -> None:
        existing = self._conn.execute(
            "SELECT version FROM games WHERE game_id = ?", [game.game_id]
        ).fetchone()

        if existing is not None:
            stored_version = existing[0]
            expected_prev = game.version - 1
            if stored_version != expected_prev:
                raise ConcurrentModificationError(
                    f"game {game.game_id}: stored version {stored_version} "
                    f"!= expected {expected_prev}"
                )
            self._update(game)
        else:
            self._insert(game)

    def delete_game(self, game_id: str) -> None:
        self._conn.execute("DELETE FROM players WHERE game_id = ?", [game_id])
        self._conn.execute("DELETE FROM actions WHERE game_id = ?", [game_id])
        self._conn.execute("DELETE FROM event_log WHERE game_id = ?", [game_id])
        self._conn.execute("DELETE FROM games WHERE game_id = ?", [game_id])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _insert(self, game: GameState) -> None:
        self._conn.execute(
            """
            INSERT INTO games VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            self._row(game),
        )
        self._upsert_players(game)
        self._upsert_actions(game)

    def _update(self, game: GameState) -> None:
        self._conn.execute(
            """
            UPDATE games SET
                guild_id=?, channel_id=?, phase=?, round=?, version=?,
                role_strategy=?, day_votes=?, night_kills_pending=?,
                seer_checked=?, bodyguard_protected=?, hunter_shot_pending=?,
                started_at=?, ended_at=?
            WHERE game_id=?
            """,
            [
                game.guild_id,
                game.channel_id,
                game.phase,
                game.round,
                game.version,
                game.role_strategy,
                json.dumps(game.day_votes),
                game.night_kills_pending,
                game.seer_checked,
                game.bodyguard_protected,
                game.hunter_shot_pending,
                game.started_at,
                game.ended_at,
                game.game_id,
            ],
        )
        self._upsert_players(game)
        self._upsert_actions(game)

    def _row(self, game: GameState) -> list:
        return [
            game.game_id,
            game.guild_id,
            game.channel_id,
            game.phase,
            game.round,
            game.version,
            game.role_strategy,
            json.dumps(game.day_votes),
            game.night_kills_pending,
            game.seer_checked,
            game.bodyguard_protected,
            game.hunter_shot_pending,
            game.started_at,
            game.ended_at,
        ]

    def _upsert_players(self, game: GameState) -> None:
        self._conn.execute("DELETE FROM players WHERE game_id = ?", [game.game_id])
        for p in game.players.values():
            self._conn.execute(
                "INSERT INTO players VALUES (?, ?, ?, ?, ?, ?)",
                [game.game_id, p.user_id, p.display_name, p.role, p.alive, p.protected],
            )

    def _upsert_actions(self, game: GameState) -> None:
        self._conn.execute("DELETE FROM actions WHERE game_id = ?", [game.game_id])
        for a in game.pending_actions.values():
            self._conn.execute(
                "INSERT INTO actions VALUES (?, ?, ?, ?)",
                [game.game_id, a.actor_id, a.action_type, a.target_id],
            )

    def _hydrate(self, row: tuple) -> GameState:
        (
            game_id,
            guild_id,
            channel_id,
            phase,
            round_,
            version,
            role_strategy,
            day_votes_json,
            night_kills_pending,
            seer_checked,
            bodyguard_protected,
            hunter_shot_pending,
            started_at,
            ended_at,
        ) = row

        players_rows = self._conn.execute(
            "SELECT user_id, display_name, role, alive, protected"
            " FROM players WHERE game_id = ?",
            [game_id],
        ).fetchall()
        players = {
            r[0]: Player(
                user_id=r[0],
                display_name=r[1],
                role=r[2],
                alive=r[3],
                protected=r[4],
            )
            for r in players_rows
        }

        action_rows = self._conn.execute(
            "SELECT actor_id, action_type, target_id FROM actions WHERE game_id = ?",
            [game_id],
        ).fetchall()
        pending_actions = {
            r[0]: Action(actor_id=r[0], action_type=r[1], target_id=r[2])
            for r in action_rows
        }

        day_votes: dict[str, str] = json.loads(day_votes_json) if day_votes_json else {}

        return GameState(
            game_id=game_id,
            guild_id=guild_id,
            channel_id=channel_id,
            phase=Phase(phase),
            round=round_,
            version=version,
            role_strategy=role_strategy,
            players=players,
            pending_actions=pending_actions,
            day_votes=day_votes,
            night_kills_pending=night_kills_pending,
            seer_checked=seer_checked,
            bodyguard_protected=bodyguard_protected,
            hunter_shot_pending=hunter_shot_pending,
            started_at=started_at,
            ended_at=ended_at,
        )
