from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

import aiohttp
import discord
from bs4 import BeautifulSoup
from discord import app_commands
from discord.ext import commands

from aira.bot import AiraBot
from utils.command_checks import registered

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChampionInfo:
    champion_id: str
    key: str
    ko_name: str
    en_name: str

    @property
    def slug(self) -> str:
        return self.champion_id.lower()


@dataclass(frozen=True)
class ChampionBuildSummary:
    win_rate: str | None
    pick_rate: str | None
    ban_rate: str | None
    runes: str | None
    skill_order: str | None
    counters: str | None
    items: str | None
    source_url: str


class ChampionDataClient:
    def __init__(self, session: aiohttp.ClientSession) -> None:
        self.session = session
        self._champions: dict[str, ChampionInfo] | None = None

    async def _get_json(self, url: str) -> Any:
        async with self.session.get(url) as response:
            response.raise_for_status()
            return await response.json(content_type=None)

    async def _get_text(self, url: str) -> str:
        headers = {
            "User-Agent": "Mozilla/5.0 AIRA Discord Bot",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        async with self.session.get(url, headers=headers) as response:
            response.raise_for_status()
            return await response.text()

    async def load_champions(self) -> dict[str, ChampionInfo]:
        if self._champions is not None:
            return self._champions

        versions = await self._get_json("https://ddragon.leagueoflegends.com/api/versions.json")
        version = versions[0]
        ko_data = await self._get_json(
            f"https://ddragon.leagueoflegends.com/cdn/{version}/data/ko_KR/champion.json"
        )
        en_data = await self._get_json(
            f"https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/champion.json"
        )

        en_by_key = {champion["key"]: champion for champion in en_data["data"].values()}
        champions: dict[str, ChampionInfo] = {}
        for champion in ko_data["data"].values():
            en_champion = en_by_key[champion["key"]]
            info = ChampionInfo(
                champion_id=champion["id"],
                key=champion["key"],
                ko_name=champion["name"],
                en_name=en_champion["name"],
            )
            aliases = {
                info.champion_id.lower(),
                info.ko_name.lower().replace(" ", ""),
                info.en_name.lower().replace(" ", ""),
            }
            for alias in aliases:
                champions[alias] = info

        self._champions = champions
        return champions

    async def find_champion(self, query: str) -> ChampionInfo | None:
        champions = await self.load_champions()
        normalized = query.strip().lower().replace(" ", "")
        return champions.get(normalized)

    async def fetch_build_summary(self, champion: ChampionInfo) -> ChampionBuildSummary:
        source_url = f"https://u.gg/lol/champions/{champion.slug}/build"
        html = await self._get_text(source_url)
        text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)

        return ChampionBuildSummary(
            win_rate=self._first_percent_after(text, "Win Rate"),
            pick_rate=self._first_percent_after(text, "Pick Rate"),
            ban_rate=self._first_percent_after(text, "Ban Rate"),
            runes=self._extract_after_labels(text, ["Runes", "Best Runes"], max_words=18),
            skill_order=self._extract_skill_order(text),
            counters=self._extract_after_labels(text, ["Counters", "Weak Against"], max_words=24),
            items=self._extract_after_labels(text, ["Items", "Starting Items", "Core Items"], max_words=24),
            source_url=source_url,
        )

    @staticmethod
    def _first_percent_after(text: str, label: str) -> str | None:
        idx = text.lower().find(label.lower())
        if idx == -1:
            return None
        match = re.search(r"\d+(?:\.\d+)?%", text[idx : idx + 160])
        return match.group(0) if match else None

    @staticmethod
    def _extract_after_labels(text: str, labels: list[str], max_words: int) -> str | None:
        lowered = text.lower()
        for label in labels:
            idx = lowered.find(label.lower())
            if idx == -1:
                continue
            chunk = text[idx + len(label) : idx + 500]
            words = [word for word in re.split(r"\s+", chunk) if word]
            cleaned = " ".join(words[:max_words]).strip(" -·|,")
            if cleaned:
                return cleaned
        return None

    @staticmethod
    def _extract_skill_order(text: str) -> str | None:
        patterns = [
            r"Skill Order\s+([QWER]\s*[>→-]\s*[QWER]\s*[>→-]\s*[QWER])",
            r"Skill Priority\s+([QWER]\s*[>→-]\s*[QWER]\s*[>→-]\s*[QWER])",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return match.group(1).replace("-", "→").replace(">", "→")
        return None


class ChampionLinks(discord.ui.View):
    def __init__(self, champion: ChampionInfo) -> None:
        super().__init__(timeout=300)
        slug = champion.slug
        self.add_item(discord.ui.Button(label="U.GG", url=f"https://u.gg/lol/champions/{slug}/build"))
        self.add_item(discord.ui.Button(label="OP.GG", url=f"https://www.op.gg/champions/{slug}/build"))
        self.add_item(discord.ui.Button(label="Lolalytics", url=f"https://lolalytics.com/lol/{slug}/build/"))


class Champion(commands.Cog):
    def __init__(self, bot: AiraBot) -> None:
        self.bot = bot
        self.session = aiohttp.ClientSession()
        self.client = ChampionDataClient(self.session)

    async def cog_unload(self) -> None:
        await self.session.close()

    @app_commands.command(name="챔피언", description="챔피언의 룬, 스킬, 상성, 아이템 통계를 조회합니다.")
    @app_commands.describe(name="예: 가렌, Garen, 아리")
    @registered()
    async def champion(self, interaction: discord.Interaction, name: str) -> None:
        await interaction.response.defer(thinking=True)

        champion = await self.client.find_champion(name)
        if champion is None:
            await interaction.followup.send(
                f"`{name}` 챔피언을 찾지 못했습니다. 예: `/챔피언 name: 가렌`",
                ephemeral=True,
            )
            return

        try:
            summary = await self.client.fetch_build_summary(champion)
        except Exception:
            LOGGER.exception("Failed to fetch champion build summary")
            summary = ChampionBuildSummary(
                win_rate=None,
                pick_rate=None,
                ban_rate=None,
                runes=None,
                skill_order=None,
                counters=None,
                items=None,
                source_url=f"https://u.gg/lol/champions/{champion.slug}/build",
            )

        embed = discord.Embed(
            title=f"{champion.ko_name} ({champion.en_name}) 통계",
            description="U.GG 기준 챔피언 빌드 요약입니다. 사이트 구조 변경 시 일부 항목은 링크로 확인해주세요.",
            color=0x7DD3FC,
            url=summary.source_url,
        )
        embed.add_field(name="승률", value=summary.win_rate or "자동 추출 실패", inline=True)
        embed.add_field(name="픽률", value=summary.pick_rate or "자동 추출 실패", inline=True)
        embed.add_field(name="밴률", value=summary.ban_rate or "자동 추출 실패", inline=True)
        embed.add_field(name="많이 드는 룬", value=summary.runes or "아래 통계 링크에서 확인", inline=False)
        embed.add_field(name="스킬 마스터 순서", value=summary.skill_order or "아래 통계 링크에서 확인", inline=False)
        embed.add_field(name="주요 상성", value=summary.counters or "아래 통계 링크에서 확인", inline=False)
        embed.add_field(name="아이템 트리", value=summary.items or "아래 통계 링크에서 확인", inline=False)
        embed.set_footer(text="Data Dragon champion lookup · U.GG build page")

        await interaction.followup.send(embed=embed, view=ChampionLinks(champion))


async def setup(bot: AiraBot) -> None:
    await bot.add_cog(Champion(bot))
