from __future__ import annotations

import datetime
import random
import time

import discord
from discord import app_commands
from discord.ext import commands

from aira.bot import AiraBot
from aira.checks import registered, require_role
from aira.db import UserRole

START_TIME = datetime.datetime.now(datetime.UTC)
EMBED_COLOR = 0xCCFFFF


def get_embed(title: str, description: str = "", color: int = EMBED_COLOR) -> discord.Embed:
    return discord.Embed(title=title, description=description, color=color)


def ping_level(ping: float) -> str:
    if ping <= 100:
        return "🔵 매우좋음"
    if ping <= 300:
        return "🟢 양호함"
    if ping <= 450:
        return "🟡 보통"
    if ping <= 600:
        return "🔴 나쁨"
    return "⚫ 매우나쁨"


def format_discord_snowflake_date(user_id: int) -> str:
    created_at = datetime.datetime.fromtimestamp(
        ((int(user_id) >> 22) + 1420070400000) / 1000,
        tz=datetime.UTC,
    )
    return f"{created_at.year}년 {created_at.month}월 {created_at.day}일"


def status_text(status: discord.Status) -> str:
    if status is discord.Status.online:
        return "🟢 온라인"
    if status is discord.Status.offline:
        return "⚫ 오프라인"
    if status is discord.Status.idle:
        return "🟡 자리 비움"
    if status is discord.Status.dnd:
        return "⛔ 방해 금지"
    return "불러오는데 실패"


class Chat(commands.Cog):
    def __init__(self, bot: AiraBot) -> None:
        self.bot = bot

    @app_commands.command(name="유저", description="AIRA 가입자 수와 서버 수를 확인합니다.")
    @registered()
    async def user_count(self, interaction: discord.Interaction) -> None:
        count = await self.bot.user_repository.count_users()
        embed = get_embed("🎮 | 게임 유저", f"AIRA의 가입자 수는 {count}명 서버는 {len(self.bot.guilds)}개 입니다")
        if self.bot.user and self.bot.user.display_avatar:
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="주사위", description="1부터 6까지 주사위를 굴립니다.")
    @registered()
    async def dice(self, interaction: discord.Interaction) -> None:
        value = random.randint(0, 5)
        await interaction.response.send_message(
            embed=get_embed("주사위 : " + [":one:", ":two:", ":three:", ":four:", ":five:", ":six:"][value])
        )

    @app_commands.command(name="정보", description="AIRA 봇 정보를 확인합니다.")
    @registered()
    async def info(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="🏷️ | **AIRA**",
            description=(
                "AIRA Made By **gimon0330**\n"
                "> Made With Discord.py\n"
                "> League of Legends records with Riot API\n"
                f"**{len(self.bot.guilds)}** SERVERS | **{len(self.bot.users)}** USERS"
            ),
            color=EMBED_COLOR,
        )
        embed.set_footer(text="AIRA")
        if self.bot.user and self.bot.user.display_avatar:
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="핑", description="Discord 지연시간과 봇 메시지 지연시간을 확인합니다.")
    @registered()
    async def ping(self, interaction: discord.Interaction) -> None:
        gateway_ping = round(1000 * self.bot.latency, 2)
        time_then = time.monotonic()
        await interaction.response.send_message(
            embed=get_embed(
                "🏓 퐁!",
                f"**디스코드 지연시간: **{gateway_ping}ms - {ping_level(gateway_ping)}\n\n"
                "**봇 메세지 지연시간**: Pinging..",
            )
        )
        message_ping = round(1000 * (time.monotonic() - time_then), 2)
        await interaction.edit_original_response(
            embed=get_embed(
                "🏓 퐁!",
                f"**디스코드 지연시간: **{gateway_ping}ms - {ping_level(gateway_ping)}\n\n"
                f"**봇 메세지 지연시간**: {message_ping}ms - {ping_level(message_ping)}",
            )
        )

    @app_commands.command(name="서버", description="AIRA가 들어간 서버 상위 목록을 확인합니다.")
    @require_role(UserRole.SUPERUSER)
    async def servers(self, interaction: discord.Interaction) -> None:
        servers = []
        for guild in self.bot.guilds:
            owner = guild.owner.name if guild.owner else "Unknown"
            servers.append([guild.name, guild.member_count or 0, owner])
        servers.sort(key=lambda x: x[1], reverse=True)

        embed = discord.Embed(title="AIRA 서버", description=f"총 {len(self.bot.guilds)} 개의 서버", color=EMBED_COLOR)
        for index, server in enumerate(servers[:10], start=1):
            embed.add_field(
                name=f"{index}위 {server[0]}",
                value=f"인원 : {server[1]}, 서버 주인 : {server[2]}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="업타임", description="봇이 켜져 있던 시간을 확인합니다.")
    @registered()
    async def uptime(self, interaction: discord.Interaction) -> None:
        delta = datetime.datetime.now(datetime.UTC) - START_TIME
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        days, hours = divmod(hours, 24)
        if days:
            time_format = f"**{days}**일 **{hours}**시간 **{minutes}**분 **{seconds}**초"
        else:
            time_format = f"**{hours}**시간 **{minutes}**분 **{seconds}**초"
        await interaction.response.send_message(f"{time_format} 동안 깨어 있었어요!")

    @app_commands.command(name="투표", description="찬반 투표를 생성합니다.")
    @app_commands.describe(내용="투표할 내용")
    @registered()
    async def vote(self, interaction: discord.Interaction, 내용: str) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                embed=get_embed("❌ | 서버내에서만 사용가능한 명령어 입니다.", color=0xFF0000),
                ephemeral=True,
            )
            return

        embed = get_embed(내용, f"By. {interaction.user.display_name}", EMBED_COLOR)
        await interaction.response.send_message(embed=embed)
        message = await interaction.original_response()
        await message.add_reaction("✅")
        await message.add_reaction("❌")

    @app_commands.command(name="프로필", description="서버 유저의 프로필을 확인합니다.")
    @app_commands.describe(user="조회할 유저. 비워두면 본인을 조회합니다.")
    @registered()
    async def profile(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                embed=get_embed("❌ | 서버내에서만 사용가능한 명령어 입니다.", color=0xFF0000),
                ephemeral=True,
            )
            return

        member = user or interaction.user
        description = f"**유저 ID** : {member.id}"
        if member.display_name != member.name:
            description = f"닉네임 : ({member.display_name})\n{description}"

        embed = discord.Embed(
            title=f"👤 | **{member.name} 님의 프로필**",
            description=description,
            color=EMBED_COLOR,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="현재 상태", value=status_text(member.status), inline=True)
        embed.add_field(name="Discord 가입 일시", value=format_discord_snowflake_date(member.id), inline=True)
        if member.joined_at:
            joined_at = member.joined_at.astimezone(datetime.UTC)
            embed.add_field(
                name="서버 가입 일시",
                value=f"{joined_at.year}년 {joined_at.month:02d}월 {joined_at.day:02d}일",
                inline=True,
            )

        if member.bot:
            embed.add_field(
                name="봇 초대장 생성",
                value=f"[초대장](https://discord.com/oauth2/authorize?client_id={member.id}&scope=bot&permissions=0)",
            )
        else:
            db_user = await self.bot.user_repository.get_user(member.id)
            embed.add_field(name="봇 권한", value=db_user.role.value if db_user else "USER", inline=True)
            embed.add_field(
                name="서버 권한",
                value="ADMIN" if member.guild_permissions.administrator else "USER",
                inline=True,
            )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="프사", description="유저의 프로필 사진을 확인합니다.")
    @app_commands.describe(user="조회할 유저. 비워두면 본인을 조회합니다.")
    @registered()
    async def profile_image(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        member = user or interaction.user
        embed = get_embed(f"🖼️ | {member.name} 님의 프로필사진")
        embed.set_image(url=member.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="초대장", description="AIRA 봇 초대 링크를 확인합니다.")
    @registered()
    async def invite(self, interaction: discord.Interaction) -> None:
        app_id = self.bot.user.id if self.bot.user else 0
        invite_url = f"https://discord.com/oauth2/authorize?client_id={app_id}&permissions=8&scope=bot%20applications.commands"
        await interaction.response.send_message(
            embed=get_embed(
                "📋 | AIRA 초대",
                f">>> [AIRA 다른 서버에 초대하기!]({invite_url})",
            )
        )


async def setup(bot: AiraBot) -> None:
    await bot.add_cog(Chat(bot))
