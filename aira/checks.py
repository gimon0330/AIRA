from __future__ import annotations

import discord
from discord import app_commands

from aira.db import UserRole


class RegisterView(discord.ui.View):
    def __init__(self, bot: discord.Client) -> None:
        super().__init__(timeout=300)
        self.bot = bot

    @discord.ui.button(label="가입하기", style=discord.ButtonStyle.primary)
    async def register(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user is None:
            await interaction.response.send_message("유저 정보를 확인할 수 없습니다.", ephemeral=True)
            return

        await self.bot.user_repository.upsert_user(interaction.user.id)
        await interaction.response.send_message(
            "가입이 완료되었습니다. 이제 명령어를 다시 사용할 수 있습니다.",
            ephemeral=True,
        )


async def ensure_registered(interaction: discord.Interaction) -> bool:
    user = await interaction.client.user_repository.get_user(interaction.user.id)
    if user is not None:
        return True

    await interaction.response.send_message(
        "AIRA를 처음 사용하는 유저입니다. 아래 버튼을 눌러 가입해주세요.",
        view=RegisterView(interaction.client),
        ephemeral=True,
    )
    return False


def registered() -> app_commands.Check:
    return app_commands.check(ensure_registered)


def require_role(minimum_role: UserRole) -> app_commands.Check:
    async def predicate(interaction: discord.Interaction) -> bool:
        user = await interaction.client.user_repository.get_user(interaction.user.id)
        if user is None:
            await ensure_registered(interaction)
            return False
        if user.has_role(minimum_role):
            return True
        await interaction.response.send_message("이 명령어를 사용할 권한이 없습니다.", ephemeral=True)
        return False

    return app_commands.check(predicate)
