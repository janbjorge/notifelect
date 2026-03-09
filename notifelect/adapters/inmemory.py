from __future__ import annotations

import dataclasses
import itertools
from typing import Any, Callable


@dataclasses.dataclass
class InMemoryBackend:
    """BackendPort implementation backed by in-process data structures.

    Useful for unit testing the election logic without any external service.
    Multiple InMemoryBackend instances sharing the same *registry* dict
    will see each other's published messages and draw from the same
    monotonic counter, simulating a real pub/sub bus.

    Usage for multi-node tests::

        registry = InMemoryBackend.create_registry()
        b1 = InMemoryBackend(_registry=registry)
        b2 = InMemoryBackend(_registry=registry)
    """

    _channel: str = dataclasses.field(default="ch_test")
    _registry: dict[str, Any] | None = dataclasses.field(
        default=None,
        repr=False,
    )

    def __post_init__(self) -> None:
        if self._registry is None:
            self._registry = self.create_registry()

    @staticmethod
    def create_registry() -> dict[str, Any]:
        """Create a shared registry for multi-node setups."""
        return {
            "listeners": {},
            "counter": itertools.count(1),
        }

    @property
    def channel(self) -> str:
        return self._channel

    def _listeners(self) -> dict[str, list[Callable[..., Any]]]:
        assert self._registry is not None
        return self._registry["listeners"]

    def _counter(self) -> itertools.count[int]:
        assert self._registry is not None
        return self._registry["counter"]

    async def next_sequence(self) -> int:
        return next(self._counter())

    async def publish(self, channel: str, payload: str) -> None:
        for callback in list(self._listeners().get(channel, [])):
            callback(payload)

    async def subscribe(
        self,
        channel: str,
        callback: Callable[..., Any],
    ) -> None:
        self._listeners().setdefault(channel, []).append(callback)

    async def unsubscribe(
        self,
        channel: str,
        callback: Callable[..., Any],
    ) -> None:
        listeners = self._listeners().get(channel, [])
        if callback in listeners:
            listeners.remove(callback)

    async def install(self) -> None:
        pass

    async def uninstall(self) -> None:
        pass
