import asyncio
import contextlib
import random
import sys
from typing import AsyncGenerator

import asyncpg

from notifelect import election
from notifelect.adapters.postgresql import PostgreSQLBackend


@contextlib.asynccontextmanager
async def connection() -> AsyncGenerator[asyncpg.Connection, None]:
    conn = await asyncpg.connect()
    try:
        yield conn
    finally:
        await conn.close()


async def process() -> None:
    await asyncio.sleep(random.random() * 2)
    async with (
        connection() as conn,
        election.Coordinator(PostgreSQLBackend(conn)),
    ):
        await asyncio.sleep(float("inf"))


async def main() -> None:
    N = int(sys.argv[1])
    processes = [process() for _ in range(N)]
    await asyncio.gather(*processes)


if __name__ == "__main__":
    asyncio.run(main())
