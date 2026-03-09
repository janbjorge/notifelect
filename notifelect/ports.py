from __future__ import annotations

from typing import Any, Callable, Protocol, runtime_checkable


@runtime_checkable
class BackendPort(Protocol):
    """Transport-agnostic interface for the election infrastructure.

    Every backend (PostgreSQL, Redis, in-memory, ...) implements this single
    protocol.  The election core depends only on this — never on concrete
    drivers or connection objects.
    """

    @property
    def channel(self) -> str:
        """The pub/sub channel name used for election messages."""
        ...

    async def next_sequence(self) -> int:
        """Acquire a monotonically increasing sequence number."""
        ...

    async def publish(self, channel: str, payload: str) -> None:
        """Broadcast *payload* to all subscribers on *channel*."""
        ...

    async def subscribe(
        self,
        channel: str,
        callback: Callable[..., Any],
    ) -> None:
        """Register *callback* to receive messages on *channel*."""
        ...

    async def unsubscribe(
        self,
        channel: str,
        callback: Callable[..., Any],
    ) -> None:
        """Remove a previously registered *callback* from *channel*."""
        ...

    async def install(self) -> None:
        """Create backend resources (e.g. PG sequence).  No-op if not needed."""
        ...

    async def uninstall(self) -> None:
        """Remove backend resources.  No-op if not needed."""
        ...
