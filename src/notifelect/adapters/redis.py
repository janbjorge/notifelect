from __future__ import annotations

import asyncio
import dataclasses
from typing import Annotated, Literal

import redis.asyncio as aioredis
from pydantic import BaseModel, BeforeValidator
from redis.asyncio.client import PubSub

from notifelect import logconfig
from notifelect.models import Channel, Listener


def _decode_bytes(v: object) -> object:
    return v.decode() if isinstance(v, bytes) else v


DecodedStr = Annotated[str, BeforeValidator(_decode_bytes)]


class RedisPubSubMessage(BaseModel):
    """Parsed representation of a Redis pub/sub message dict."""

    type: Literal["message"]
    channel: DecodedStr
    data: DecodedStr


@dataclasses.dataclass
class RedisConfig:
    """Names of the Redis resources used by the election backend.

    Override to avoid collisions when multiple services share the same
    Redis instance, or when a key prefix is required::

        config = RedisConfig(
            channel="myapp:ch_notifelect",
            sequence_key="myapp:seq_notifelect",
        )
        backend = RedisBackend(client, pubsub, config=config)
    """

    channel: Channel = dataclasses.field(default=Channel("ch_notifelect"))
    sequence_key: str = dataclasses.field(default="seq_notifelect")


@dataclasses.dataclass
class RedisBackend:
    """BackendPort implementation using Redis PUBLISH/SUBSCRIBE and INCR sequences.

    Requires the ``redis`` extra::

        pip install notifelect[redis]

    The caller is responsible for creating and closing both the command client
    and the pub/sub connection.  This keeps connection lifecycle outside the
    backend, consistent with how ``PostgreSQLBackend`` expects the caller to
    own and close the ``asyncpg.Connection``::

        import redis.asyncio as aioredis
        from notifelect.adapters.redis import RedisBackend

        client = aioredis.Redis.from_url("redis://localhost:6379")
        pubsub = client.pubsub()
        try:
            async with Coordinator(RedisBackend(client, pubsub)) as result:
                ...
        finally:
            await pubsub.close()
            await client.aclose()

    Custom resource names::

        from notifelect.adapters.redis import RedisBackend, RedisConfig

        config = RedisConfig(
            channel="myapp:ch_notifelect",
            sequence_key="myapp:seq_notifelect",
        )
        async with Coordinator(RedisBackend(client, pubsub, config=config)) as result:
            ...
    """

    client: aioredis.Redis
    pubsub: PubSub
    config: RedisConfig = dataclasses.field(default_factory=RedisConfig)

    _listeners: dict[str, list[Listener]] = dataclasses.field(
        default_factory=dict,
        init=False,
    )
    _reader_task: asyncio.Task[None] | None = dataclasses.field(
        default=None,
        init=False,
    )

    @property
    def channel(self) -> str:
        return self.config.channel

    async def next_sequence(self) -> int:
        """Atomically increment and return the sequence counter."""
        return int(await self.client.incr(self.config.sequence_key))

    async def publish(self, channel: str, payload: str) -> None:
        await self.client.publish(channel, payload)

    async def subscribe(self, channel: str, callback: Listener) -> None:
        self._listeners.setdefault(channel, []).append(callback)
        await self.pubsub.subscribe(channel)
        if self._reader_task is None or self._reader_task.done():
            self._reader_task = asyncio.create_task(self._reader())

    async def unsubscribe(self, channel: str, callback: Listener) -> None:
        listeners = self._listeners.get(channel, [])
        if callback in listeners:
            listeners.remove(callback)
        if not listeners:
            self._listeners.pop(channel, None)
            await self.pubsub.unsubscribe(channel)
        if not self._listeners and self._reader_task is not None:
            self._reader_task.cancel()
            self._reader_task = None

    async def install(self) -> None:
        """No-op: Redis INCR auto-creates keys."""

    async def uninstall(self) -> None:
        """Delete the sequence key."""
        await self.client.delete(self.config.sequence_key)

    async def _reader(self) -> None:
        """Dispatch incoming pub/sub messages to registered listeners."""
        async for raw in self.pubsub.listen():
            try:
                message = RedisPubSubMessage.model_validate(raw)
            except Exception:
                logconfig.logger.debug("Ignoring non-message pub/sub event: %s", raw)
                continue
            for callback in list(self._listeners.get(message.channel, [])):
                try:
                    callback(message.data)
                except Exception:
                    logconfig.logger.exception("Listener raised an exception")
