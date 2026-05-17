"""Standalone bootstrap for running WerewolfCog without flatusbot.

Usage:
    DISCORD_TOKEN=<token> python -m werewolf.standalone.main

For flatusbot integration, add to flatus/bot/main.py setup():

    import duckdb
    from werewolf.core.engine import WerewolfEngine
    from werewolf.discord.cog import WerewolfCog
    from werewolf.discord.timer import DiscordTimerService
    from werewolf.infra.repo import DuckDBGameRepository

    db_conn = duckdb.connect("/data/werewolf.db")
    repo = DuckDBGameRepository(db_conn)
    engine = WerewolfEngine(repo)
    timer = DiscordTimerService()
    messaging = CogMessaging(bot)          # see CogMessaging below
    await bot.add_cog(WerewolfCog(engine, repo, messaging))
"""

from __future__ import annotations

import asyncio
import os

import discord
import duckdb
from discord.ext import commands

from werewolf.core.engine import WerewolfEngine
from werewolf.discord.cog import WerewolfCog
from werewolf.infra.repo import DuckDBGameRepository


class CogMessaging:
    """Minimal MessagingProtocol that sends via the discord Bot."""

    def __init__(self, bot: commands.Bot) -> None:
        self._bot = bot

    async def send_channel(self, channel_id: int, message) -> None:
        channel = self._bot.get_channel(channel_id)
        if channel is None:
            channel = await self._bot.fetch_channel(channel_id)
        if isinstance(message, discord.Embed):
            await channel.send(embed=message)
        else:
            await channel.send(str(message))

    async def send_dm(self, user_id: int, message) -> None:
        user = self._bot.get_user(user_id)
        if user is None:
            user = await self._bot.fetch_user(user_id)
        if isinstance(message, discord.Embed):
            await user.send(embed=message)
        else:
            await user.send(str(message))


def _build_bot(db_path: str) -> commands.Bot:
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    bot = commands.Bot(command_prefix="!", intents=intents)

    @bot.event
    async def on_ready() -> None:
        print(f"Logged in as {bot.user} (ID: {bot.user.id})")

    @bot.event
    async def on_message(message: discord.Message) -> None:
        if message.author.bot:
            return
        if message.content.startswith(bot.command_prefix):
            await bot.process_commands(message)

    async def _setup() -> None:
        db_conn = duckdb.connect(db_path)
        repo = DuckDBGameRepository(db_conn)
        engine = WerewolfEngine(repo)
        messaging = CogMessaging(bot)
        await bot.add_cog(WerewolfCog(engine, repo, messaging))

    bot.setup_hook = _setup
    return bot


def run() -> None:
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN environment variable is not set")
    db_path = os.environ.get("WEREWOLF_DB_PATH", "/data/werewolf.db")
    bot = _build_bot(db_path)
    asyncio.run(bot.start(token))


if __name__ == "__main__":
    run()
