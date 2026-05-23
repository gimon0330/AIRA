from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    discord_token: str
    riot_api_key: str
    discord_guild_id: int | None = None
    database_url: str | None = None
    github_webhook_secret: str | None = None
    port: int = 8080
    superuser_ids: frozenset[int] = frozenset()


def _get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _get_int_env(name: str) -> int | None:
    value = os.getenv(name)
    return int(value) if value else None


def _get_int_set_env(name: str) -> frozenset[int]:
    value = os.getenv(name)
    if not value:
        return frozenset()
    return frozenset(int(item.strip()) for item in value.split(",") if item.strip())


def load_settings() -> Settings:
    load_dotenv()

    return Settings(
        discord_token=_get_required_env("DISCORD_TOKEN"),
        riot_api_key=_get_required_env("RIOT_API_KEY"),
        discord_guild_id=_get_int_env("DISCORD_GUILD_ID"),
        database_url=os.getenv("DATABASE_URL"),
        github_webhook_secret=os.getenv("GITHUB_WEBHOOK_SECRET"),
        port=int(os.getenv("PORT", "8080")),
        superuser_ids=_get_int_set_env("SUPERUSER_IDS"),
    )
