"""WerewolfCog: Discord commands for the Werewolf game."""

from __future__ import annotations

import discord
from discord.ext import commands

from werewolf.core.engine import (
    ActionNotAllowedError,
    InvalidPhaseError,
    WerewolfEngine,
)
from werewolf.core.models import Action
from werewolf.core.protocols import GameRepository, MessagingProtocol
from werewolf.core.roles import Seer
from werewolf.discord import formatter


class WerewolfCog(commands.Cog):
    def __init__(
        self,
        engine: WerewolfEngine,
        repo: GameRepository,
        messaging: MessagingProtocol,
    ) -> None:
        self._engine = engine
        self._repo = repo
        self._messaging = messaging

    # ------------------------------------------------------------------
    # Channel commands
    # ------------------------------------------------------------------

    @commands.command(name="new")
    async def new_game(self, ctx: commands.Context) -> None:
        if not isinstance(ctx.channel, discord.TextChannel):
            return
        guild_id = str(ctx.guild.id)
        channel_id = str(ctx.channel.id)
        if self._repo.get_active_game(guild_id) is not None:
            await ctx.send(formatter.game_already_active())
            return
        self._engine.create_game(guild_id, channel_id)
        await ctx.send(formatter.game_created())

    @commands.command(name="join")
    async def join_game(self, ctx: commands.Context) -> None:
        if not isinstance(ctx.channel, discord.TextChannel):
            return
        game = self._repo.get_active_game(str(ctx.guild.id))
        if game is None:
            await ctx.send(formatter.no_active_game())
            return
        try:
            game = self._engine.join(
                game.game_id, str(ctx.author.id), ctx.author.display_name
            )
            await ctx.send(
                formatter.player_joined(ctx.author.display_name, len(game.players))
            )
        except InvalidPhaseError as e:
            await ctx.send(str(e))

    @commands.command(name="leave")
    async def leave_game(self, ctx: commands.Context) -> None:
        if not isinstance(ctx.channel, discord.TextChannel):
            return
        game = self._repo.get_active_game(str(ctx.guild.id))
        if game is None:
            await ctx.send(formatter.no_active_game())
            return
        try:
            self._engine.leave(game.game_id, str(ctx.author.id))
            await ctx.send(formatter.player_left(ctx.author.display_name))
        except InvalidPhaseError as e:
            await ctx.send(str(e))

    @commands.command(name="start")
    async def start_game(self, ctx: commands.Context) -> None:
        if not isinstance(ctx.channel, discord.TextChannel):
            return
        game = self._repo.get_active_game(str(ctx.guild.id))
        if game is None:
            await ctx.send(formatter.no_active_game())
            return
        try:
            game = self._engine.start(game.game_id)
            await ctx.send(formatter.game_started(len(game.players)))
            for player in game.players.values():
                await self._messaging.send_dm(
                    int(player.user_id),
                    formatter.role_assigned(player.role or "unknown"),
                )
        except (InvalidPhaseError, ActionNotAllowedError) as e:
            await ctx.send(str(e))

    @commands.command(name="end")
    async def end_game(self, ctx: commands.Context) -> None:
        if not isinstance(ctx.channel, discord.TextChannel):
            return
        game = self._repo.get_active_game(str(ctx.guild.id))
        if game is None:
            await ctx.send(formatter.no_active_game())
            return
        self._engine.force_end(game.game_id)
        await ctx.send(formatter.game_ended())

    @commands.command(name="status")
    async def status(self, ctx: commands.Context) -> None:
        if not isinstance(ctx.channel, discord.TextChannel):
            return
        game = self._repo.get_active_game(str(ctx.guild.id))
        if game is None:
            await ctx.send(formatter.no_active_game())
            return
        state = self._engine.get_public_state(game.game_id)
        await ctx.send(formatter.public_state(state))

    @commands.command(name="vote")
    async def vote(self, ctx: commands.Context, target: str | None = None) -> None:
        if not isinstance(ctx.channel, discord.TextChannel):
            return
        game = self._repo.get_active_game(str(ctx.guild.id))
        if game is None:
            await ctx.send(formatter.no_active_game())
            return
        try:
            self._engine.vote(game.game_id, str(ctx.author.id), target)
            await ctx.send(formatter.vote_recorded(ctx.author.display_name))
        except (InvalidPhaseError, ActionNotAllowedError) as e:
            await ctx.send(str(e))

    # ------------------------------------------------------------------
    # DM commands
    # ------------------------------------------------------------------

    @commands.command(name="see")
    async def see(self, ctx: commands.Context, target: str | None = None) -> None:
        if not isinstance(ctx.channel, discord.DMChannel):
            return
        user_id = str(ctx.author.id)
        game = self._repo.get_game_by_player(user_id)
        if game is None:
            await ctx.send(formatter.no_active_game())
            return
        if target is None:
            await ctx.send(formatter.wrong_phase("No target specified."))
            return
        target_player = game.players.get(target)
        if target_player is None or not target_player.alive:
            await ctx.send(formatter.wrong_phase("Invalid target."))
            return
        result = Seer.investigate(target_player.role or "")
        action = Action(actor_id=user_id, action_type="investigate", target_id=target)
        try:
            self._engine.submit_night_action(game.game_id, user_id, action)
            await ctx.send(
                formatter.investigation_result(target_player.display_name, result)
            )
        except (InvalidPhaseError, ActionNotAllowedError) as e:
            await ctx.send(str(e))

    @commands.command(name="kill")
    async def kill(self, ctx: commands.Context, target: str | None = None) -> None:
        if not isinstance(ctx.channel, discord.DMChannel):
            return
        user_id = str(ctx.author.id)
        game = self._repo.get_game_by_player(user_id)
        if game is None:
            await ctx.send(formatter.no_active_game())
            return
        action = Action(actor_id=user_id, action_type="kill", target_id=target)
        try:
            self._engine.submit_night_action(game.game_id, user_id, action)
            await ctx.send(formatter.action_submitted())
        except (InvalidPhaseError, ActionNotAllowedError) as e:
            await ctx.send(str(e))

    @commands.command(name="guard")
    async def guard(self, ctx: commands.Context, target: str | None = None) -> None:
        if not isinstance(ctx.channel, discord.DMChannel):
            return
        user_id = str(ctx.author.id)
        game = self._repo.get_game_by_player(user_id)
        if game is None:
            await ctx.send(formatter.no_active_game())
            return
        action = Action(actor_id=user_id, action_type="protect", target_id=target)
        try:
            self._engine.submit_night_action(game.game_id, user_id, action)
            await ctx.send(formatter.action_submitted())
        except (InvalidPhaseError, ActionNotAllowedError) as e:
            await ctx.send(str(e))

    @commands.command(name="shoot")
    async def shoot(self, ctx: commands.Context, target: str | None = None) -> None:
        if not isinstance(ctx.channel, discord.DMChannel):
            return
        user_id = str(ctx.author.id)
        game = self._repo.get_game_by_player(user_id)
        if game is None:
            await ctx.send(formatter.no_active_game())
            return
        try:
            self._engine.hunter_shoot(game.game_id, user_id, target or "")
            await ctx.send(formatter.action_submitted())
        except (InvalidPhaseError, ActionNotAllowedError) as e:
            await ctx.send(str(e))
