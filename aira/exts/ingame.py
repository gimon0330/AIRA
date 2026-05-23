from __future__ import annotations

import asyncio
import datetime
import logging
from collections import Counter
from dataclasses import dataclass
from typing import Any

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from aira.bot import AiraBot
from aira.exts.league import parse_riot_id, safe_defer
from utils.command_checks import registered
from utils.riot import RiotApiError, RiotClient

LOGGER = logging.getLogger(__name__)

QUEUE_NAMES = {
    400: "일반 교차 선택",
    420: "랭크 솔로/듀오",
    430: "일반 비공개 선택",
    440: "랭크 자유",
    450: "무작위 총력전",
    490: "빠른 대전",
    700: "격전",
    830: "입문 봇",
    840: "초급 봇",
    850: "중급 봇",
    900: "URF",
    1020: "단일 챔피언",
    1300: "돌격! 넥서스",
    1400: "궁극기 주문서",
    1700: "아레나",
}

MAP_NAMES = {
    11: "소환사의 협곡",
    12: "칼바람 나락",
    21: "넥서스 블리츠",
    30: "링 오브 래스",
}

POSITION_NAMES = {
    "TOP": "탑",
    "JUNGLE": "정글",
    "MIDDLE": "미드",
    "BOTTOM": "원딜",
    "UTILITY": "서폿",
    "NONE": "없음",
    "": "알 수 없음",
}


@dataclass(frozen=True)
class ChampionStatic:
    champion_id: str
    ko_name: str
    en_name: str


@dataclass(frozen=True)
class SpellStatic:
    spell_id: str
    ko_name: str


@dataclass(frozen=True)
class RecentStats:
    games: int
    wins: int
    primary_position: str
    primary_position_count: int
    streak_type: str
    streak_count: int
    current_champion_games: int

    @property
    def win_rate(self) -> float:
        return 0.0 if self.games == 0 else self.wins / self.games * 100


class StaticDataClient:
    def __init__(self, session: aiohttp.ClientSession) -> None:
        self.session = session
        self.version: str | None = None
        self.champions_by_key: dict[int, ChampionStatic] | None = None
        self.spells_by_key: dict[int, SpellStatic] | None = None

    async def _get_json(self, url: str) -> Any:
        async with self.session.get(url) as response:
            response.raise_for_status()
            return await response.json(content_type=None)

    async def load(self) -> None:
        if self.champions_by_key is not None and self.spells_by_key is not None:
            return

        versions = await self._get_json("https://ddragon.leagueoflegends.com/api/versions.json")
        self.version = versions[0]
        champion_data = await self._get_json(
            f"https://ddragon.leagueoflegends.com/cdn/{self.version}/data/ko_KR/champion.json"
        )
        spell_data = await self._get_json(
            f"https://ddragon.leagueoflegends.com/cdn/{self.version}/data/ko_KR/summoner.json"
        )

        self.champions_by_key = {
            int(champion["key"]): ChampionStatic(
                champion_id=champion["id"],
                ko_name=champion["name"],
                en_name=champion["id"],
            )
            for champion in champion_data["data"].values()
        }
        self.spells_by_key = {
            int(spell["key"]): SpellStatic(
                spell_id=spell["id"],
                ko_name=spell["name"],
            )
            for spell in spell_data["data"].values()
        }

    def champion_name(self, champion_id: int) -> str:
        champion = (self.champions_by_key or {}).get(champion_id)
        return champion.ko_name if champion else f"Champion {champion_id}"

    def spell_name(self, spell_id: int) -> str:
        spell = (self.spells_by_key or {}).get(spell_id)
        return spell.ko_name if spell else f"Spell {spell_id}"

    def champion_square_url(self, champion_id: int) -> str | None:
        champion = (self.champions_by_key or {}).get(champion_id)
        if champion is None:
            return None
        version = self.version or "14.24.1"
        return f"https://ddragon.leagueoflegends.com/cdn/{version}/img/champion/{champion.champion_id}.png"


class InGame(commands.Cog):
    def __init__(self, bot: AiraBot) -> None:
        self.bot = bot
        self.session = aiohttp.ClientSession()
        self.riot = RiotClient(bot.settings.riot_api_key, self.session)
        self.static = StaticDataClient(self.session)

    async def cog_unload(self) -> None:
        await self.session.close()

    async def get_active_game(self, puuid: str) -> dict[str, Any]:
        url = f"https://kr.api.riotgames.com/lol/spectator/v5/active-games/by-summoner/{puuid}"
        return await self.riot._get(url)

    async def get_match_detail(self, match_id: str) -> dict[str, Any]:
        url = f"https://asia.api.riotgames.com/lol/match/v5/matches/{match_id}"
        return await self.riot._get(url)

    async def analyze_recent_stats(self, puuid: str, current_champion_id: int) -> RecentStats:
        match_ids = await self.riot.get_match_ids(puuid, count=20)
        details = await asyncio.gather(
            *(self.get_match_detail(match_id) for match_id in match_ids),
            return_exceptions=True,
        )

        wins: list[bool] = []
        positions: list[str] = []
        current_champion_games = 0

        for detail in details:
            if isinstance(detail, Exception):
                continue
            participants = detail.get("info", {}).get("participants", [])
            participant = next((p for p in participants if p.get("puuid") == puuid), None)
            if participant is None:
                continue

            wins.append(bool(participant.get("win")))
            position = participant.get("teamPosition") or participant.get("individualPosition") or ""
            if position:
                positions.append(position)
            if int(participant.get("championId", 0)) == current_champion_id:
                current_champion_games += 1

        position_counter = Counter(positions)
        primary_position, primary_position_count = position_counter.most_common(1)[0] if position_counter else ("", 0)
        streak_type = "없음"
        streak_count = 0
        if wins:
            first = wins[0]
            streak_count = 0
            for result in wins:
                if result == first:
                    streak_count += 1
                else:
                    break
            streak_type = "연승" if first else "연패"

        return RecentStats(
            games=len(wins),
            wins=sum(1 for win in wins if win),
            primary_position=primary_position,
            primary_position_count=primary_position_count,
            streak_type=streak_type,
            streak_count=streak_count,
            current_champion_games=current_champion_games,
        )

    @staticmethod
    def game_duration_text(game: dict[str, Any]) -> str:
        if game.get("gameLength"):
            total_seconds = int(game["gameLength"])
        elif game.get("gameStartTime"):
            started_at = datetime.datetime.fromtimestamp(game["gameStartTime"] / 1000, tz=datetime.UTC)
            total_seconds = int((datetime.datetime.now(datetime.UTC) - started_at).total_seconds())
        else:
            return "알 수 없음"

        minutes, seconds = divmod(max(total_seconds, 0), 60)
        return f"{minutes}분 {seconds:02d}초"

    @staticmethod
    def lane_note(stats: RecentStats, spell_names: list[str]) -> str:
        primary = POSITION_NAMES.get(stats.primary_position, "알 수 없음")
        has_smite = "강타" in spell_names or "Smite" in spell_names
        if has_smite and stats.primary_position and stats.primary_position != "JUNGLE":
            return f"정글 가능성 · 주라인 {primary}"
        if has_smite:
            return "정글"
        if stats.primary_position_count == 0:
            return "주라인 부족"
        return f"주라인 {primary} {stats.primary_position_count}판"

    def participant_line(self, participant: dict[str, Any], stats: RecentStats | None) -> str:
        riot_id = participant.get("riotId")
        if not riot_id:
            riot_id = participant.get("gameName") or participant.get("summonerName") or "Unknown"
            tag_line = participant.get("tagLine")
            if tag_line:
                riot_id = f"{riot_id}#{tag_line}"

        champion_id = int(participant.get("championId", 0))
        champion_name = self.static.champion_name(champion_id)
        spell_names = [
            self.static.spell_name(int(participant.get("spell1Id", 0))),
            self.static.spell_name(int(participant.get("spell2Id", 0))),
        ]

        if stats is None or stats.games == 0:
            detail = "최근 기록 없음"
        else:
            lane_note = self.lane_note(stats, spell_names)
            streak = f"{stats.streak_count}{stats.streak_type}" if stats.streak_count >= 2 else "연승/연패 없음"
            detail = (
                f"최근 {stats.games}판 {stats.wins}승 {stats.games - stats.wins}패 {stats.win_rate:.0f}% · "
                f"{lane_note} · {streak} · 현챔 {stats.current_champion_games}판"
            )

        return f"**{champion_name}** · {riot_id}\n{spell_names[0]} / {spell_names[1]} · {detail}"

    @app_commands.command(name="인게임", description="Riot ID의 현재 게임 정보와 참가자 최근 전적을 조회합니다.")
    @app_commands.describe(riot_id="예: Hide on bush#KR1. 비워두면 즐겨찾기 소환사를 조회합니다.")
    @registered()
    async def ingame(self, interaction: discord.Interaction, riot_id: str | None = None) -> None:
        if not await safe_defer(interaction):
            return

        try:
            user = await self.bot.user_repository.get_user(interaction.user.id)
            target_riot_id = riot_id.strip() if riot_id else user.favorite_riot_id if user else None
            if not target_riot_id:
                await interaction.followup.send(
                    "조회할 Riot ID가 없습니다. `/즐겨찾기 riot_id: Hide on bush#KR1`로 즐겨찾기를 먼저 저장하거나 `/인게임 riot_id: ...`로 직접 입력해주세요.",
                    ephemeral=True,
                )
                return

            game_name, tag_line = parse_riot_id(target_riot_id)
            account = await self.riot.get_account_by_riot_id(game_name, tag_line)
            game = await self.get_active_game(account.puuid)
            await self.static.load()
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        except RiotApiError as exc:
            if exc.status == 404:
                await interaction.followup.send("현재 게임 중이 아닙니다.", ephemeral=True)
                return
            LOGGER.warning("Riot API error: %s %s", exc.status, exc.message)
            await interaction.followup.send(
                f"Riot API 요청에 실패했습니다. 상태 코드: {exc.status}\n{exc.message}",
                ephemeral=True,
            )
            return
        except Exception:
            LOGGER.exception("Unexpected error while handling ingame command")
            await interaction.followup.send("인게임 정보를 불러오는 중 알 수 없는 오류가 발생했습니다.", ephemeral=True)
            return

        participants = game.get("participants", [])
        stats_results = await asyncio.gather(
            *(
                self.analyze_recent_stats(
                    participant.get("puuid", ""),
                    int(participant.get("championId", 0)),
                )
                for participant in participants
                if participant.get("puuid")
            ),
            return_exceptions=True,
        )
        stats_by_puuid: dict[str, RecentStats] = {}
        stat_index = 0
        for participant in participants:
            puuid = participant.get("puuid")
            if not puuid:
                continue
            result = stats_results[stat_index]
            stat_index += 1
            if isinstance(result, Exception):
                LOGGER.warning("Failed to analyze recent stats for %s: %s", puuid, result)
                continue
            stats_by_puuid[puuid] = result

        queue_id = int(game.get("gameQueueConfigId", 0) or 0)
        map_id = int(game.get("mapId", 0) or 0)
        game_mode = game.get("gameMode", "알 수 없음")
        queue_name = QUEUE_NAMES.get(queue_id, f"Queue {queue_id}")
        map_name = MAP_NAMES.get(map_id, f"Map {map_id}")
        duration = self.game_duration_text(game)

        embed = discord.Embed(
            title=f"{account.game_name}#{account.tag_line} 현재 게임",
            description=f"{map_name} · {queue_name} · {game_mode}\n진행 시간: **{duration}**",
            color=0x7DD3FC,
        )

        for team_id, team_name in [(100, "BLUE TEAM"), (200, "RED TEAM")]:
            team_participants = [p for p in participants if int(p.get("teamId", 0)) == team_id]
            lines = []
            for participant in team_participants:
                stats = stats_by_puuid.get(participant.get("puuid", ""))
                lines.append(self.participant_line(participant, stats))
            embed.add_field(
                name=team_name,
                value="\n\n".join(lines)[:1024] or "정보 없음",
                inline=False,
            )

        bans = game.get("bannedChampions", [])
        if bans:
            ban_names = [self.static.champion_name(int(ban.get("championId", 0))) for ban in bans if int(ban.get("championId", 0)) > 0]
            if ban_names:
                embed.add_field(name="밴", value=", ".join(ban_names[:10]), inline=False)

        requester = next((p for p in participants if p.get("puuid") == account.puuid), None)
        if requester:
            thumbnail_url = self.static.champion_square_url(int(requester.get("championId", 0)))
            if thumbnail_url:
                embed.set_thumbnail(url=thumbnail_url)

        embed.set_footer(text="Spectator API · 최근 20게임은 Match-V5 기준")
        await interaction.followup.send(embed=embed)


async def setup(bot: AiraBot) -> None:
    await bot.add_cog(InGame(bot))
