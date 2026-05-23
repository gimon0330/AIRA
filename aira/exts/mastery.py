from __future__ import annotations

import logging
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


@dataclass(frozen=True)
class ChampionMeta:
    champion_id: str
    key: int
    ko_name: str
    en_name: str


class Mastery(commands.Cog):
    def __init__(self, bot: AiraBot) -> None:
        self.bot = bot
        self.session = aiohttp.ClientSession()
        self.riot = RiotClient(bot.settings.riot_api_key, self.session)
        self._champions_by_key: dict[int, ChampionMeta] | None = None
        self._ddragon_version: str | None = None

    async def cog_unload(self) -> None:
        await self.session.close()

    async def _get_json(self, url: str) -> Any:
        async with self.session.get(url) as response:
            response.raise_for_status()
            return await response.json(content_type=None)

    async def load_champions(self) -> dict[int, ChampionMeta]:
        if self._champions_by_key is not None:
            return self._champions_by_key

        versions = await self._get_json("https://ddragon.leagueoflegends.com/api/versions.json")
        self._ddragon_version = versions[0]
        ko_data = await self._get_json(
            f"https://ddragon.leagueoflegends.com/cdn/{self._ddragon_version}/data/ko_KR/champion.json"
        )
        en_data = await self._get_json(
            f"https://ddragon.leagueoflegends.com/cdn/{self._ddragon_version}/data/en_US/champion.json"
        )
        en_by_key = {int(champion["key"]): champion for champion in en_data["data"].values()}

        champions: dict[int, ChampionMeta] = {}
        for champion in ko_data["data"].values():
            key = int(champion["key"])
            en_champion = en_by_key[key]
            champions[key] = ChampionMeta(
                champion_id=champion["id"],
                key=key,
                ko_name=champion["name"],
                en_name=en_champion["name"],
            )

        self._champions_by_key = champions
        return champions

    async def get_masteries(self, puuid: str) -> list[dict[str, Any]]:
        url = f"https://kr.api.riotgames.com/lol/champion-mastery/v4/champion-masteries/by-puuid/{puuid}"
        return await self.riot._get(url)

    def champion_square_url(self, champion: ChampionMeta) -> str:
        version = self._ddragon_version or "14.24.1"
        return f"https://ddragon.leagueoflegends.com/cdn/{version}/img/champion/{champion.champion_id}.png"

    @app_commands.command(name="숙련도", description="Riot ID의 챔피언 숙련도 상위 5개를 조회합니다.")
    @app_commands.describe(riot_id="예: Hide on bush#KR1. 비워두면 즐겨찾기 소환사를 조회합니다.")
    @registered()
    async def mastery(self, interaction: discord.Interaction, riot_id: str | None = None) -> None:
        if not await safe_defer(interaction):
            return

        try:
            user = await self.bot.user_repository.get_user(interaction.user.id)
            target_riot_id = riot_id.strip() if riot_id else user.favorite_riot_id if user else None
            if not target_riot_id:
                await interaction.followup.send(
                    "조회할 Riot ID가 없습니다. `/즐겨찾기 riot_id: Hide on bush#KR1`로 즐겨찾기를 먼저 저장하거나 `/숙련도 riot_id: ...`로 직접 입력해주세요.",
                    ephemeral=True,
                )
                return

            game_name, tag_line = parse_riot_id(target_riot_id)
            account = await self.riot.get_account_by_riot_id(game_name, tag_line)
            champions = await self.load_champions()
            masteries = await self.get_masteries(account.puuid)
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
            LOGGER.exception("Unexpected error while handling mastery command")
            await interaction.followup.send("숙련도를 불러오는 중 알 수 없는 오류가 발생했습니다.", ephemeral=True)
            return

        top_masteries = masteries[:5]
        if not top_masteries:
            await interaction.followup.send("숙련도 정보를 찾지 못했습니다.", ephemeral=True)
            return

        lines = []
        top_champion: ChampionMeta | None = None
        for rank, mastery in enumerate(top_masteries, start=1):
            champion = champions.get(int(mastery["championId"]))
            if champion is None:
                name = f"Champion {mastery['championId']}"
            else:
                name = f"{champion.ko_name} ({champion.en_name})"
                if rank == 1:
                    top_champion = champion

            level = mastery.get("championLevel", 0)
            points = mastery.get("championPoints", 0)
            lines.append(f"{rank}. {name} · Lv.{level} · {points:,}점")

        embed = discord.Embed(
            title=f"{account.game_name}#{account.tag_line} 숙련도 Top 5",
            description="\n".join(lines),
            color=0x7DD3FC,
        )
        if top_champion is not None:
            embed.set_thumbnail(url=self.champion_square_url(top_champion))
        embed.set_footer(text="Riot Champion-Mastery API · Data Dragon")
        await interaction.followup.send(embed=embed)


async def setup(bot: AiraBot) -> None:
    await bot.add_cog(Mastery(bot))
