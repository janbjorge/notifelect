from __future__ import annotations

import asyncio
import contextlib
from datetime import timedelta
from typing import AsyncGenerator, Callable

import pytest
import redis.asyncio as aioredis

from notifelect.adapters.redis import RedisBackend
from notifelect.core.election import Coordinator, ElectionResult
from notifelect.core.settings import Settings


@contextlib.asynccontextmanager
async def _managed_backend(
    make_client: Callable[[], aioredis.Redis],
) -> AsyncGenerator[RedisBackend, None]:
    client = make_client()
    pubsub = client.pubsub()
    try:
        yield RedisBackend(client, pubsub)
    finally:
        await pubsub.aclose()


@pytest.mark.parametrize("N", (1, 2, 3, 5, 25))
async def test_one_winner(
    N: int,
    create_redis_client: Callable[[], aioredis.Redis],
) -> None:
    async def process() -> ElectionResult:
        settings = Settings(
            election_interval=timedelta(seconds=0.1),
            election_timeout=timedelta(seconds=0.05),
        )
        async with (
            _managed_backend(create_redis_client) as backend,
            Coordinator(backend, settings=settings) as result,
        ):
            await result.round_complete.wait()
            return result

    results = await asyncio.gather(*[process() for _ in range(N)])
    assert sum(r.winner for r in results) == 1
