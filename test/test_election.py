from __future__ import annotations

import asyncio
import contextlib
from datetime import timedelta
from typing import AsyncGenerator, Awaitable, Callable

import asyncpg
import pytest

from notifelect.adapters.postgresql import PostgreSQLBackend
from notifelect.core.election import Coordinator, ElectionResult
from notifelect.core.settings import Settings


@contextlib.asynccontextmanager
async def _managed_connection(
    create_pg_connection: Callable[[], Awaitable[asyncpg.Connection]],
) -> AsyncGenerator[asyncpg.Connection, None]:
    conn = await create_pg_connection()
    try:
        yield conn
    finally:
        await conn.close()


@pytest.mark.parametrize("N", (1, 2, 3, 5, 25))
async def test_one_winner(
    N: int,
    create_pg_connection: Callable[[], Awaitable[asyncpg.Connection]],
) -> None:
    async def process() -> ElectionResult:
        settings = Settings(
            election_interval=timedelta(seconds=0.5),
            election_timeout=timedelta(seconds=0.1),
        )
        async with (
            _managed_connection(create_pg_connection) as conn,
            Coordinator(PostgreSQLBackend(conn), settings=settings) as result,
        ):
            await asyncio.sleep(settings.election_interval.total_seconds() * 2)
            return result

    results = await asyncio.gather(*[process() for _ in range(N)])
    assert sum(r.winner for r in results) == 1
