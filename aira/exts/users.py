from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from aira.bot import AiraBot
from aira.exts.league import parse_riot_id
from utils.command_checks import registered


class Users(commands.Cog):
    def __init__(self, bot: AiraBot) -> None:
        self.bot = bot

    @app_commands.command(name="내정보", description="AIRA 가입 정보와 즐겨찾기 소환사를 확인합니다.")
    @registered()
    async def profile(self, interaction: discord.Interaction) -> None:
        user = await self.bot.user_repository.get_user(interaction.user.id)
        if user is None:
            await interaction.response.send_message("가입 정보를 찾지 못했습니다.", ephemeral=True)
            return

        embed = discord.Embed(title="내 정보", color=0x7DD3FC)
        embed.add_field(name="Discord ID", value=str(user.discord_id), inline=False)
        embed.add_field(name="권한", value=user.role.value, inline=False)
        embed.add_field(name="즐겨찾기 소환사", value=user.favorite_riot_id or "없음", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="즐겨찾기", description="/전적에서 기본으로 조회할 Riot ID를 저장합니다.")
    @app_commands.describe(riot_id="예: Hide on bush#KR1")
    @registered()
    async def favorite(self, interaction: discord.Interaction, riot_id: str) -> None:
        riot_id = riot_id.strip()
        try:
            game_name, tag_line = parse_riot_id(riot_id)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        normalized_riot_id = f"{game_name}#{tag_line}"
        user = await self.bot.user_repository.set_favorite_riot_id(
            interaction.user.id,
            normalized_riot_id,
        )
        await interaction.response.send_message(
            f"즐겨찾기 소환사를 `{user.favorite_riot_id}`로 저장했습니다. 이제 `/전적`만 입력해도 이 소환사를 조회합니다.",
            ephemeral=True,
        )


async def setup(bot: AiraBot) -> None:
    await bot.add_cog(Users(bot))
