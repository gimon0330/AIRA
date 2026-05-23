from __future__ import annotations

import logging
from pathlib import Path

import discord
from discord.ext import commands

from aira.config import Settings

LOGGER = logging.getLogger(__name__)
EXTENSIONS_DIR = Path(__file__).parent / "exts"


class AiraBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.settings = settings

    async def setup_hook(self) -> None:
        for ext_path in sorted(EXTENSIONS_DIR.glob("*.py")):
            if ext_path.name.startswith("_"):
                continue

            extension_name = f"aira.exts.{ext_path.stem}"
            await self.load_extension(extension_name)
            LOGGER.info("Loaded extension %s", extension_name)

        if self.settings.discord_guild_id is not None:
            guild = discord.Object(id=self.settings.discord_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            LOGGER.info("Synced app commands to guild %s", self.settings.discord_guild_id)
        else:
            await self.tree.sync()
            LOGGER.info("Synced global app commands")

    async def on_ready(self) -> None:
        if self.user is None:
            return
        LOGGER.info("Logged in as %s (%s)", self.user, self.user.id)
        await self.change_presence(activity=discord.Game(name="/전적"))
