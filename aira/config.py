from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    discord_token: str
    riot_api_key: str
    discord_guild_id: int | None = None


def _get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def load_settings() -> Settings:
    load_dotenv()

    guild_id = os.getenv("DISCORD_GUILD_ID")
    return Settings(
        discord_token=_get_required_env("DISCORD_TOKEN"),
        riot_api_key=_get_required_env("RIOT_API_KEY"),
        discord_guild_id=int(guild_id) if guild_id else None,
    )
