from __future__ import annotations

import enum
from dataclasses import dataclass

import aiosqlite
import asyncpg


class UserRole(str, enum.Enum):
    USER = "User"
    ADMINISTRATOR = "Administrator"
    SUPERUSER = "SuperUser"


ROLE_LEVEL = {
    UserRole.USER: 0,
    UserRole.ADMINISTRATOR: 1,
    UserRole.SUPERUSER: 2,
}


@dataclass(frozen=True)
class DiscordUser:
    discord_id: int
    role: UserRole
    favorite_riot_id: str | None

    def has_role(self, minimum_role: UserRole) -> bool:
        return ROLE_LEVEL[self.role] >= ROLE_LEVEL[minimum_role]


class UserRepository:
    async def setup(self) -> None:
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError

    async def get_user(self, discord_id: int) -> DiscordUser | None:
        raise NotImplementedError

    async def create_user(self, discord_id: int, role: UserRole = UserRole.USER) -> DiscordUser:
        raise NotImplementedError

    async def upsert_user(self, discord_id: int, role: UserRole = UserRole.USER) -> DiscordUser:
        user = await self.get_user(discord_id)
        if user is not None:
            return user
        return await self.create_user(discord_id, role)

    async def set_role(self, discord_id: int, role: UserRole) -> DiscordUser:
        raise NotImplementedError

    async def set_favorite_riot_id(self, discord_id: int, riot_id: str) -> DiscordUser:
        raise NotImplementedError


class PostgresUserRepository(UserRepository):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.pool: asyncpg.Pool | None = None

    async def setup(self) -> None:
        self.pool = await asyncpg.create_pool(self.database_url)
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS discord_users (
                    discord_id BIGINT PRIMARY KEY,
                    role TEXT NOT NULL DEFAULT 'User',
                    favorite_riot_id TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()

    @staticmethod
    def _from_record(record: asyncpg.Record | None) -> DiscordUser | None:
        if record is None:
            return None
        return DiscordUser(
            discord_id=int(record["discord_id"]),
            role=UserRole(record["role"]),
            favorite_riot_id=record["favorite_riot_id"],
        )

    async def get_user(self, discord_id: int) -> DiscordUser | None:
        assert self.pool is not None
        record = await self.pool.fetchrow(
            "SELECT discord_id, role, favorite_riot_id FROM discord_users WHERE discord_id = $1",
            discord_id,
        )
        return self._from_record(record)

    async def create_user(self, discord_id: int, role: UserRole = UserRole.USER) -> DiscordUser:
        assert self.pool is not None
        record = await self.pool.fetchrow(
            """
            INSERT INTO discord_users (discord_id, role)
            VALUES ($1, $2)
            ON CONFLICT (discord_id) DO UPDATE SET updated_at = now()
            RETURNING discord_id, role, favorite_riot_id
            """,
            discord_id,
            role.value,
        )
        user = self._from_record(record)
        assert user is not None
        return user

    async def set_role(self, discord_id: int, role: UserRole) -> DiscordUser:
        assert self.pool is not None
        record = await self.pool.fetchrow(
            """
            INSERT INTO discord_users (discord_id, role)
            VALUES ($1, $2)
            ON CONFLICT (discord_id) DO UPDATE SET role = $2, updated_at = now()
            RETURNING discord_id, role, favorite_riot_id
            """,
            discord_id,
            role.value,
        )
        user = self._from_record(record)
        assert user is not None
        return user

    async def set_favorite_riot_id(self, discord_id: int, riot_id: str) -> DiscordUser:
        assert self.pool is not None
        record = await self.pool.fetchrow(
            """
            UPDATE discord_users
            SET favorite_riot_id = $2, updated_at = now()
            WHERE discord_id = $1
            RETURNING discord_id, role, favorite_riot_id
            """,
            discord_id,
            riot_id,
        )
        user = self._from_record(record)
        if user is None:
            user = await self.create_user(discord_id)
            return await self.set_favorite_riot_id(user.discord_id, riot_id)
        return user


class SqliteUserRepository(UserRepository):
    def __init__(self, database_path: str = "aira.sqlite3") -> None:
        self.database_path = database_path
        self.conn: aiosqlite.Connection | None = None

    async def setup(self) -> None:
        self.conn = await aiosqlite.connect(self.database_path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS discord_users (
                discord_id INTEGER PRIMARY KEY,
                role TEXT NOT NULL DEFAULT 'User',
                favorite_riot_id TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn is not None:
            await self.conn.close()

    @staticmethod
    def _from_row(row: aiosqlite.Row | None) -> DiscordUser | None:
        if row is None:
            return None
        return DiscordUser(
            discord_id=int(row["discord_id"]),
            role=UserRole(row["role"]),
            favorite_riot_id=row["favorite_riot_id"],
        )

    async def get_user(self, discord_id: int) -> DiscordUser | None:
        assert self.conn is not None
        async with self.conn.execute(
            "SELECT discord_id, role, favorite_riot_id FROM discord_users WHERE discord_id = ?",
            (discord_id,),
        ) as cursor:
            return self._from_row(await cursor.fetchone())

    async def create_user(self, discord_id: int, role: UserRole = UserRole.USER) -> DiscordUser:
        assert self.conn is not None
        await self.conn.execute(
            "INSERT OR IGNORE INTO discord_users (discord_id, role) VALUES (?, ?)",
            (discord_id, role.value),
        )
        await self.conn.commit()
        user = await self.get_user(discord_id)
        assert user is not None
        return user

    async def set_role(self, discord_id: int, role: UserRole) -> DiscordUser:
        assert self.conn is not None
        await self.create_user(discord_id, role)
        await self.conn.execute(
            "UPDATE discord_users SET role = ?, updated_at = CURRENT_TIMESTAMP WHERE discord_id = ?",
            (role.value, discord_id),
        )
        await self.conn.commit()
        user = await self.get_user(discord_id)
        assert user is not None
        return user

    async def set_favorite_riot_id(self, discord_id: int, riot_id: str) -> DiscordUser:
        assert self.conn is not None
        await self.create_user(discord_id)
        await self.conn.execute(
            """
            UPDATE discord_users
            SET favorite_riot_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE discord_id = ?
            """,
            (riot_id, discord_id),
        )
        await self.conn.commit()
        user = await self.get_user(discord_id)
        assert user is not None
        return user


def build_user_repository(database_url: str | None) -> UserRepository:
    if database_url:
        return PostgresUserRepository(database_url)
    return SqliteUserRepository()
