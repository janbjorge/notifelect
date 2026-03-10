from __future__ import annotations

import dataclasses
import itertools
from typing import TypedDict

from notifelect.models import Listener


class Registry(TypedDict):
    listeners: dict[str, list[Listener]]
    counter: itertools.count[int]


@dataclasses.dataclass
class InMemoryBackend:
    """BackendPort implementation backed by in-process data structures.

    Useful for unit testing the election logic without any external service.
    Multiple InMemoryBackend instances sharing the same *registry* dict
    will see each other's published messages and draw from the same
    monotonic counter, simulating a real pub/sub bus.

    Usage for multi-node tests::

        registry = InMemoryBackend.create_registry()
        b1 = InMemoryBackend(registry=registry)
        b2 = InMemoryBackend(registry=registry)
    """

    channel_name: str = dataclasses.field(default="ch_test")
    registry: Registry | None = dataclasses.field(
        default=None,
        repr=False,
    )

    def __post_init__(self) -> None:
        if self.registry is None:
            self.registry = self.create_registry()

    @staticmethod
    def create_registry() -> Registry:
        """Create a shared registry for multi-node setups."""
        return {
            "listeners": {},
            "counter": itertools.count(1),
        }

    @property
    def channel(self) -> str:
        return self.channel_name

    def get_listeners(self) -> dict[str, list[Listener]]:
        assert self.registry is not None
        return self.registry["listeners"]

    def get_counter(self) -> itertools.count[int]:
        assert self.registry is not None
        return self.registry["counter"]

    async def next_sequence(self) -> int:
        return next(self.get_counter())

    async def publish(self, channel: str, payload: str) -> None:
        for callback in list(self.get_listeners().get(channel, [])):
            callback(payload)

    async def subscribe(
        self,
        channel: str,
        callback: Listener,
    ) -> None:
        self.get_listeners().setdefault(channel, []).append(callback)

    async def unsubscribe(
        self,
        channel: str,
        callback: Listener,
    ) -> None:
        listeners = self.get_listeners().get(channel, [])
        if callback in listeners:
            listeners.remove(callback)

    async def install(self) -> None:
        pass

    async def uninstall(self) -> None:
        pass
