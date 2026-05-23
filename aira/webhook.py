from __future__ import annotations

import hmac
import logging
from hashlib import sha256

from aiohttp import web

LOGGER = logging.getLogger(__name__)


class GitHubWebhookServer:
    def __init__(self, bot) -> None:
        self.bot = bot
        self.app = web.Application()
        self.app.router.add_get("/health", self.health)
        self.app.router.add_post("/github/webhook", self.github_webhook)
        self.runner: web.AppRunner | None = None
        self.site: web.TCPSite | None = None

    async def start(self) -> None:
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, "0.0.0.0", self.bot.settings.port)
        await self.site.start()
        LOGGER.info("GitHub webhook server started on port %s", self.bot.settings.port)

    async def stop(self) -> None:
        if self.runner is not None:
            await self.runner.cleanup()

    async def health(self, request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    def _verify_signature(self, body: bytes, signature: str | None) -> bool:
        secret = self.bot.settings.github_webhook_secret
        if not secret or not signature or not signature.startswith("sha256="):
            return False

        expected = "sha256=" + hmac.new(secret.encode(), body, sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    async def github_webhook(self, request: web.Request) -> web.Response:
        body = await request.read()
        signature = request.headers.get("X-Hub-Signature-256")
        event = request.headers.get("X-GitHub-Event")

        if not self._verify_signature(body, signature):
            return web.json_response({"ok": False, "error": "invalid signature"}, status=401)

        if event != "push":
            return web.json_response({"ok": True, "ignored": event})

        try:
            reloaded = await self.bot.reload_extensions()
        except Exception as exc:
            LOGGER.exception("Failed to reload extensions from GitHub webhook")
            return web.json_response({"ok": False, "error": str(exc)}, status=500)

        LOGGER.info("Reloaded extensions from GitHub webhook: %s", ", ".join(reloaded))
        return web.json_response({"ok": True, "reloaded": reloaded})
