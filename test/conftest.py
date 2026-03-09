from __future__ import annotations

from typing import Any, AsyncGenerator, Awaitable, Callable, Generator

import asyncpg
import pytest
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer, None, None]:
    with PostgresContainer("postgres:16") as pg:
        yield pg


@pytest.fixture(scope="session", autouse=True)
async def _install_schema(postgres_container: PostgresContainer) -> AsyncGenerator[None, None]:
    from notifelect.queries import SQLBuilder

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
) -> Callable[[], Awaitable[Any]]:
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
