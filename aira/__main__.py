from __future__ import annotations

import logging

from aira.bot import AiraBot
from config import load_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

settings = load_settings()
AiraBot(settings).run(settings.discord_token)
