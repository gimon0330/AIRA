from __future__ import annotations

import logging
from collections import Counter

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from aira.bot import AiraBot
from utils.command_checks import registered
from utils.riot import LeagueEntry, MatchSummary, RiotApiError, RiotClient

LOGGER = logging.getLogger(__name__)

QUEUE_NAMES = {
    "RANKED_SOLO_5x5": "솔로랭크",
    "RANKED_FLEX_SR": "자유랭크",
}


def parse_riot_id(riot_id: str) -> tuple[str, str]:
    if "#" not in riot_id:
        raise ValueError("Riot ID는 이름#태그 형식으로 입력해야 합니다. 예: Hide on bush#KR1")

    game_name, tag_line = riot_id.rsplit("#", 1)
    game_name = game_name.strip()
    tag_line = tag_line.strip()

    if not game_name or not tag_line:
        raise ValueError("Riot ID의 이름과 태그를 모두 입력해야 합니다.")

    return game_name, tag_line


def parse_league_entries(payload: list[dict]) -> list[LeagueEntry]:
    return [
        LeagueEntry(
            queue_type=entry["queueType"],
            tier=entry["tier"],
            rank=entry["rank"],
            league_points=entry["leaguePoints"],
            wins=entry["wins"],
            losses=entry["losses"],
        )
        for entry in payload
    ]


def format_rank(entries: list[LeagueEntry], queue_type: str) -> str:
    entry = next((entry for entry in entries if entry.queue_type == queue_type), None)
    if entry is None:
        return "Unranked"

    queue_name = QUEUE_NAMES.get(entry.queue_type, entry.queue_type)
    return (
        f"{queue_name}: {entry.tier} {entry.rank} {entry.league_points} LP\n"
        f"{entry.wins}승 {entry.losses}패 · 승률 {entry.win_rate:.1f}%"
    )


def format_match_line(match: MatchSummary) -> str:
    result = "승" if match.win else "패"
    minutes = max(match.game_duration_seconds // 60, 1)
    cs_per_min = match.cs / minutes
    return (
        f"`{result}` {match.champion_name} · KDA {match.kda_text} · "
        f"CS {match.cs} ({cs_per_min:.1f}/m) · 시야 {match.vision_score}"
    )


def format_most_played_champions(matches: list[MatchSummary]) -> str:
    champion_counts = Counter(match.champion_name for match in matches)
    if not champion_counts:
        return "최근 매치를 찾지 못했습니다."

    return "\n".join(
        f"{rank}. {champion} · {count}판"
        for rank, (champion, count) in enumerate(champion_counts.most_common(3), start=1)
    )


async def safe_defer(interaction: discord.Interaction) -> bool:
    if interaction.response.is_done():
        return True
    try:
        await interaction.response.defer(thinking=True)
        return True
    except discord.NotFound:
        LOGGER.warning("Interaction expired before defer")
        return False


class League(commands.Cog):
    def __init__(self, bot: AiraBot) -> None:
        self.bot = bot
        self.session = aiohttp.ClientSession()
        self.riot = RiotClient(bot.settings.riot_api_key, self.session)

    async def cog_unload(self) -> None:
        await self.session.close()

    async def get_league_entries_by_puuid(self, puuid: str) -> list[LeagueEntry]:
        url = f"https://kr.api.riotgames.com/lol/league/v4/entries/by-puuid/{puuid}"
        payload = await self.riot._get(url)
        return parse_league_entries(payload)

    @app_commands.command(name="전적", description="Riot ID로 리그오브레전드 최근 전적을 조회합니다.")
    @app_commands.describe(riot_id="예: Hide on bush#KR1. 비워두면 즐겨찾기 소환사를 조회합니다.")
    @registered()
    async def record(self, interaction: discord.Interaction, riot_id: str | None = None) -> None:
        if not await safe_defer(interaction):
            return

        try:
            user = await self.bot.user_repository.get_user(interaction.user.id)
            target_riot_id = riot_id.strip() if riot_id else user.favorite_riot_id if user else None
            if not target_riot_id:
                await interaction.followup.send(
                    "조회할 Riot ID가 없습니다. `/즐겨찾기 riot_id: Hide on bush#KR1`로 즐겨찾기를 먼저 저장하거나 `/전적 riot_id: ...`로 직접 입력해주세요.",
                    ephemeral=True,
                )
                return

            game_name, tag_line = parse_riot_id(target_riot_id)
            account = await self.riot.get_account_by_riot_id(game_name, tag_line)
            summoner = await self.riot.get_summoner_by_puuid(account.puuid)
            entries = await self.get_league_entries_by_puuid(account.puuid)
            match_ids = await self.riot.get_match_ids(account.puuid, count=20)
            matches = []
            for match_id in match_ids:
                matches.append(await self.riot.get_match_summary(match_id, account.puuid))
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        except RiotApiError as exc:
            LOGGER.warning("Riot API error: %s %s", exc.status, exc.message)
            await interaction.followup.send(
                f"Riot API 요청에 실패했습니다. 상태 코드: {exc.status}\n{exc.message}",
                ephemeral=True,
            )
            return
        except Exception:
            LOGGER.exception("Unexpected error while handling record command")
            await interaction.followup.send("전적을 불러오는 중 알 수 없는 오류가 발생했습니다.", ephemeral=True)
            return

        profile_icon_id = summoner.get("profileIconId", 0)
        summoner_level = summoner.get("summonerLevel", 0)
        recent_matches = matches[:5]
        win_count = sum(1 for match in recent_matches if match.win)

        embed = discord.Embed(
            title=f"{account.game_name}#{account.tag_line}",
            description=(
                f"최근 {len(recent_matches)}게임 {win_count}승 {len(recent_matches) - win_count}패\n"
                f"소환사 레벨 {summoner_level}"
            ),
            color=0x7DD3FC,
        )
        embed.set_thumbnail(
            url=(
                "https://ddragon.leagueoflegends.com/cdn/14.24.1/img/profileicon/"
                f"{profile_icon_id}.png"
            )
        )
        embed.add_field(name="솔로랭크", value=format_rank(entries, "RANKED_SOLO_5x5"), inline=False)
        embed.add_field(name="자유랭크", value=format_rank(entries, "RANKED_FLEX_SR"), inline=False)
        embed.add_field(
            name="최근 20판 모스트 챔피언",
            value=format_most_played_champions(matches),
            inline=False,
        )
        embed.add_field(
            name="최근 게임",
            value="\n".join(format_match_line(match) for match in recent_matches) or "최근 매치를 찾지 못했습니다.",
            inline=False,
        )
        embed.set_footer(text="Riot API · KR/ASIA routing")
        await interaction.followup.send(embed=embed)


async def setup(bot: AiraBot) -> None:
    await bot.add_cog(League(bot))
