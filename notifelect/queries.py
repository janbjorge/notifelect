from __future__ import annotations

import asyncio
import dataclasses
import os
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    import asyncpg


from . import models


def add_prefix(string: str) -> str:
    """
    Appends a predefined prefix from environment variables to
    the given string, typically used for database object names.
    """
    return f"{os.environ.get('NOTIFELECT_PREFIX', '')}{string}"


@dataclasses.dataclass
class QueryBuilder:
    channel: Final[models.Channel] = dataclasses.field(
        default_factory=lambda: models.Channel(add_prefix("ch_notifelect")),
        kw_only=True,
    )

    sequence: Final[str] = dataclasses.field(
        default_factory=lambda: add_prefix("seq_notifelect"),
        kw_only=True,
    )

    def create_install_query(self) -> str:
        """
        Generates the SQL query string to create necessary database objects.
        """
        return f"""
    CREATE SEQUENCE {self.sequence} START 1;
    """

    def create_uninstall_query(self) -> str:
        """
        Generates the SQL query string to remove all database structures
        related to the job queue system.
        """
        return f"""
    DROP SEQUENCE {self.sequence};
    """

    def create_next_sequence_query(self) -> str:
        return f"""
    SELECT nextval('{self.sequence}');
    """

    def create_emit_query(self) -> str:
        return f"""
    SELECT pg_notify('{self.channel}', $1);
    """


@dataclasses.dataclass
class Queries:
    connection: asyncpg.Connection
    query_builder: QueryBuilder = dataclasses.field(
        default_factory=QueryBuilder,
    )
    lock: asyncio.Lock = dataclasses.field(
        default_factory=asyncio.Lock,
        init=False,
    )

    async def install(self) -> None:
        async with self.lock:
            await self.connection.execute(self.query_builder.create_install_query())

    async def uninstall(self) -> None:
        async with self.lock:
            await self.connection.execute(self.query_builder.create_uninstall_query())

    async def sequence(self) -> models.Sequence:
        async with self.lock:
            return models.Sequence(
                await self.connection.fetchval(
                    self.query_builder.create_next_sequence_query(),
                )
            )

    async def emit(self, event: models.BaseModel) -> None:
        async with self.lock:
            await self.connection.execute(
                self.query_builder.create_emit_query(),
                event.model_dump_json(),
            )
