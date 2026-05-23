from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import aiohttp


class RiotApiError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True)
class RiotAccount:
    game_name: str
    tag_line: str
    puuid: str


@dataclass(frozen=True)
class LeagueEntry:
    queue_type: str
    tier: str
    rank: str
    league_points: int
    wins: int
    losses: int

    @property
    def win_rate(self) -> float:
        games = self.wins + self.losses
        return 0.0 if games == 0 else self.wins / games * 100


@dataclass(frozen=True)
class MatchSummary:
    champion_name: str
    kills: int
    deaths: int
    assists: int
    win: bool
    total_minions_killed: int
    neutral_minions_killed: int
    vision_score: int
    game_duration_seconds: int

    @property
    def cs(self) -> int:
        return self.total_minions_killed + self.neutral_minions_killed

    @property
    def kda_text(self) -> str:
        return f"{self.kills}/{self.deaths}/{self.assists}"


class RiotClient:
    def __init__(self, api_key: str, session: aiohttp.ClientSession) -> None:
        self._api_key = api_key
        self._session = session

    async def _get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        headers = {"X-Riot-Token": self._api_key}
        async with self._session.get(url, headers=headers, params=params) as response:
            if response.status == 204:
                return None

            payload = await response.json(content_type=None)
            if response.status >= 400:
                message = payload.get("status", {}).get("message", "Riot API request failed")
                raise RiotApiError(response.status, message)
            return payload

    async def get_account_by_riot_id(self, game_name: str, tag_line: str) -> RiotAccount:
        url = (
            "https://asia.api.riotgames.com/riot/account/v1/accounts/by-riot-id/"
            f"{game_name}/{tag_line}"
        )
        payload = await self._get(url)
        return RiotAccount(
            game_name=payload["gameName"],
            tag_line=payload["tagLine"],
            puuid=payload["puuid"],
        )

    async def get_summoner_by_puuid(self, puuid: str) -> dict[str, Any]:
        url = f"https://kr.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}"
        return await self._get(url)

    async def get_league_entries(self, encrypted_summoner_id: str) -> list[LeagueEntry]:
        url = (
            "https://kr.api.riotgames.com/lol/league/v4/entries/by-summoner/"
            f"{encrypted_summoner_id}"
        )
        payload = await self._get(url)
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

    async def get_match_ids(self, puuid: str, count: int = 5) -> list[str]:
        url = f"https://asia.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids"
        return await self._get(url, params={"start": 0, "count": count})

    async def get_match_summary(self, match_id: str, puuid: str) -> MatchSummary:
        url = f"https://asia.api.riotgames.com/lol/match/v5/matches/{match_id}"
        payload = await self._get(url)
        participants = payload["info"]["participants"]
        participant = next(user for user in participants if user["puuid"] == puuid)
        return MatchSummary(
            champion_name=participant["championName"],
            kills=participant["kills"],
            deaths=participant["deaths"],
            assists=participant["assists"],
            win=participant["win"],
            total_minions_killed=participant["totalMinionsKilled"],
            neutral_minions_killed=participant["neutralMinionsKilled"],
            vision_score=participant["visionScore"],
            game_duration_seconds=payload["info"]["gameDuration"],
        )
