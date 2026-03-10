from __future__ import annotations

from typing import AsyncGenerator, Awaitable, Callable, Generator

import asyncpg
import pytest
import redis.asyncio as aioredis
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer, None, None]:
    with PostgresContainer("postgres:16") as pg:
        yield pg


@pytest.fixture(scope="session", autouse=True)
async def _install_schema(postgres_container: PostgresContainer) -> AsyncGenerator[None, None]:
    from notifelect.adapters.postgresql import SQLBuilder

    conn = await asyncpg.connect(
        host=postgres_container.get_container_host_ip(),
        port=int(postgres_container.get_exposed_port(5432)),
        user=postgres_container.username,
        password=postgres_container.password,
        database=postgres_container.dbname,
    )
    try:
        await conn.execute(SQLBuilder().install_sql())
    finally:
        await conn.close()
    yield


@pytest.fixture()
def create_pg_connection(
    postgres_container: PostgresContainer,
) -> Callable[[], Awaitable[asyncpg.Connection]]:
    """Returns a callable that creates a new asyncpg connection (a coroutine)."""

    async def _connect() -> asyncpg.Connection:
        return await asyncpg.connect(
            host=postgres_container.get_container_host_ip(),
            port=int(postgres_container.get_exposed_port(5432)),
            user=postgres_container.username,
            password=postgres_container.password,
            database=postgres_container.dbname,
        )

    return _connect


# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def redis_container() -> Generator[RedisContainer, None, None]:
    with RedisContainer("redis:7") as rc:
        yield rc


@pytest.fixture()
async def create_redis_client(
    redis_container: RedisContainer,
) -> AsyncGenerator[Callable[[], aioredis.Redis], None]:
    """Yields a factory that creates a new async Redis client per node.

    All clients are closed after the test.
    """
    clients: list[aioredis.Redis] = []

    def _make_client() -> aioredis.Redis:
        client = aioredis.Redis(
            host=redis_container.get_container_host_ip(),
            port=int(redis_container.get_exposed_port(6379)),
        )
        clients.append(client)
        return client

    yield _make_client

    for client in clients:
        await client.aclose()
