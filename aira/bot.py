from __future__ import annotations

import logging
from pathlib import Path

import discord
from discord.ext import commands

from aira.config import Settings
from aira.db import UserRole, build_user_repository
from aira.webhook import GitHubWebhookServer

LOGGER = logging.getLogger(__name__)
EXTENSIONS_DIR = Path(__file__).parent / "exts"


class AiraBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.settings = settings
        self.user_repository = build_user_repository(settings.database_url)
        self.webhook_server = GitHubWebhookServer(self)

    async def setup_hook(self) -> None:
        await self.user_repository.setup()
        for discord_id in self.settings.superuser_ids:
            await self.user_repository.set_role(discord_id, UserRole.SUPERUSER)

        for ext_path in sorted(EXTENSIONS_DIR.glob("*.py")):
            if ext_path.name.startswith("_"):
                continue

            extension_name = f"aira.exts.{ext_path.stem}"
            await self.load_extension(extension_name)
            LOGGER.info("Loaded extension %s", extension_name)

        if self.settings.github_webhook_secret:
            await self.webhook_server.start()

        await self.sync_app_commands()

    async def sync_app_commands(self) -> None:
        if self.settings.discord_guild_id is not None:
            guild = discord.Object(id=self.settings.discord_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            LOGGER.info("Synced app commands to guild %s", self.settings.discord_guild_id)
        else:
            await self.tree.sync()
            LOGGER.info("Synced global app commands")

    async def reload_extensions(self) -> list[str]:
        reloaded = []
        for extension_name in sorted(self.extensions):
            await self.reload_extension(extension_name)
            reloaded.append(extension_name)
        await self.sync_app_commands()
        return reloaded

    async def close(self) -> None:
        await self.webhook_server.stop()
        await self.user_repository.close()
        await super().close()

    async def on_ready(self) -> None:
        if self.user is None:
            return
        LOGGER.info("Logged in as %s (%s)", self.user, self.user.id)
        await self.change_presence(activity=discord.Game(name="/전적"))
