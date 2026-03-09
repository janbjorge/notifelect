from __future__ import annotations

import asyncio
import contextlib
from datetime import timedelta
from typing import Any, AsyncGenerator, Awaitable, Callable

import asyncpg
import pytest

from notifelect.election_manager import Coordinator, Outcome, Settings


@contextlib.asynccontextmanager
async def _managed_connection(
    create_pg_connection: Callable[[], Awaitable[Any]],
) -> AsyncGenerator[asyncpg.Connection, None]:
    conn = await create_pg_connection()
    try:
        yield conn
    finally:
        await conn.close()


@pytest.mark.parametrize("N", (1, 2, 3, 5, 25))
async def test_one_winner(
    N: int,
    create_pg_connection: Callable[[], Awaitable[Any]],
) -> None:
    async def process() -> Outcome:
        settings = Settings(
            election_interval=timedelta(seconds=0.5),
            election_timeout=timedelta(seconds=0.1),
        )
        async with (
            _managed_connection(create_pg_connection) as conn,
            Coordinator(conn, settings=settings) as outcome,
        ):
            await asyncio.sleep(settings.election_interval.total_seconds() * 2)
            return outcome

    outcomes = await asyncio.gather(*[process() for _ in range(N)])
    assert sum(o.winner for o in outcomes) == 1
