from __future__ import annotations

import asyncio
import dataclasses
import os
from typing import Final

import asyncpg

from notifelect import models
from notifelect.models import Listener


def with_prefix(name: str) -> str:
    """Prepend the NOTIFELECT_PREFIX environment variable to a database object name."""
    return f"{os.environ.get('NOTIFELECT_PREFIX', '')}{name}"


@dataclasses.dataclass
class SQLBuilder:
    channel: Final[models.Channel] = dataclasses.field(
        default_factory=lambda: models.Channel(with_prefix("ch_notifelect")),
        kw_only=True,
    )

    sequence_name: Final[str] = dataclasses.field(
        default_factory=lambda: with_prefix("seq_notifelect"),
        kw_only=True,
    )

    def install_sql(self) -> str:
        return f"CREATE SEQUENCE {self.sequence_name} START 1;"

    def uninstall_sql(self) -> str:
        return f"DROP SEQUENCE {self.sequence_name};"

    def next_sequence_sql(self) -> str:
        return f"SELECT nextval('{self.sequence_name}');"

    def notify_sql(self) -> str:
        return f"SELECT pg_notify('{self.channel}', $1);"


@dataclasses.dataclass
class PostgreSQLBackend:
    """BackendPort implementation using PostgreSQL NOTIFY/LISTEN and sequences."""

    connection: asyncpg.Connection
    sql: SQLBuilder = dataclasses.field(default_factory=SQLBuilder)
    lock: asyncio.Lock = dataclasses.field(default_factory=asyncio.Lock, init=False)

    @property
    def channel(self) -> str:
        return self.sql.channel

    async def next_sequence(self) -> int:
        async with self.lock:
            return int(await self.connection.fetchval(self.sql.next_sequence_sql()))

    async def publish(self, channel: str, payload: str) -> None:
        async with self.lock:
            await self.connection.execute(
                self.sql.notify_sql(),
                payload,
            )

    async def subscribe(
        self,
        channel: str,
        callback: Listener,
    ) -> None:
        await self.connection.add_listener(channel, callback)

    async def unsubscribe(
        self,
        channel: str,
        callback: Listener,
    ) -> None:
        await self.connection.remove_listener(channel, callback)

    async def install(self) -> None:
        async with self.lock:
            await self.connection.execute(self.sql.install_sql())

    async def uninstall(self) -> None:
        async with self.lock:
            await self.connection.execute(self.sql.uninstall_sql())
