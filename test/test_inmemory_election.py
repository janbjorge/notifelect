"""Unit tests for election logic using the InMemoryBackend — no PostgreSQL required."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from notifelect.adapters.inmemory import InMemoryBackend
from notifelect.adapters.postgresql import PostgreSQLBackend
from notifelect.core.election import Coordinator, ElectionResult
from notifelect.core.settings import Settings
from notifelect.ports import BackendPort


def _fast_settings() -> Settings:
    return Settings(
        election_interval=timedelta(seconds=0.05),
        election_timeout=timedelta(seconds=0.05),
    )


# ---------------------------------------------------------------------------
# BackendPort protocol conformance
# ---------------------------------------------------------------------------


async def test_inmemory_satisfies_backend_port() -> None:
    backend = InMemoryBackend()
    assert isinstance(backend, BackendPort)


async def test_inmemory_next_sequence_is_monotonic() -> None:
    backend = InMemoryBackend()
    values = [await backend.next_sequence() for _ in range(10)]
    assert values == sorted(values)
    assert len(set(values)) == 10


async def test_inmemory_publish_subscribe() -> None:
    received: list[str] = []
    backend = InMemoryBackend()
    await backend.subscribe("ch", lambda payload: received.append(payload))
    await backend.publish("ch", "hello")
    assert received == ["hello"]


async def test_inmemory_unsubscribe() -> None:
    received: list[str] = []

    def cb(payload: str) -> None:
        received.append(payload)

    backend = InMemoryBackend()
    await backend.subscribe("ch", cb)
    await backend.publish("ch", "a")
    await backend.unsubscribe("ch", cb)
    await backend.publish("ch", "b")
    assert received == ["a"]


async def test_inmemory_shared_registry() -> None:
    """Two backends sharing a registry see each other's messages."""
    registry = InMemoryBackend.create_registry()
    b1 = InMemoryBackend(registry=registry)
    b2 = InMemoryBackend(registry=registry)

    received: list[str] = []
    await b2.subscribe("ch", lambda p: received.append(p))
    await b1.publish("ch", "cross")
    assert received == ["cross"]


async def test_inmemory_shared_counter() -> None:
    """Two backends sharing a registry draw from the same sequence counter."""
    registry = InMemoryBackend.create_registry()
    b1 = InMemoryBackend(registry=registry)
    b2 = InMemoryBackend(registry=registry)

    s1 = await b1.next_sequence()
    s2 = await b2.next_sequence()
    assert s1 != s2
    assert s2 > s1


async def test_inmemory_install_uninstall_are_noop() -> None:
    backend = InMemoryBackend()
    await backend.install()
    await backend.uninstall()


# ---------------------------------------------------------------------------
# Single-node election
# ---------------------------------------------------------------------------


async def test_single_node_wins() -> None:
    """A lone node must declare itself the winner."""
    backend = InMemoryBackend()
    settings = _fast_settings()

    async with Coordinator(backend, settings=settings) as result:
        await result.round_complete.wait()
        assert result.winner is True


# ---------------------------------------------------------------------------
# Multi-node election (in-memory)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("N", (2, 3, 5))
async def test_one_winner_inmemory(N: int) -> None:
    """Exactly one winner among N coordinators sharing an in-memory bus."""
    registry = InMemoryBackend.create_registry()

    async def run_node() -> ElectionResult:
        backend = InMemoryBackend(registry=registry)
        settings = _fast_settings()
        async with Coordinator(backend, settings=settings) as result:
            await result.round_complete.wait()
            return result

    results = await asyncio.gather(*[run_node() for _ in range(N)])
    assert sum(r.winner for r in results) == 1


# ---------------------------------------------------------------------------
# ElectionResult is mutable and reflects latest round
# ---------------------------------------------------------------------------


async def test_election_result_object_identity() -> None:
    """The ElectionResult returned by __aenter__ is the same object mutated each round."""
    backend = InMemoryBackend()
    settings = _fast_settings()

    async with Coordinator(backend, settings=settings) as result:
        first_id = id(result)
        await result.round_complete.wait()
        assert id(result) == first_id


# ---------------------------------------------------------------------------
# Coordinator lifecycle
# ---------------------------------------------------------------------------


async def test_coordinator_cleans_up_listeners() -> None:
    """After exiting the context manager, no listeners remain on the channel."""
    registry = InMemoryBackend.create_registry()
    backend = InMemoryBackend(registry=registry)
    settings = _fast_settings()

    async with Coordinator(backend, settings=settings):
        assert len(registry["listeners"].get(backend.channel, [])) > 0

    assert len(registry["listeners"].get(backend.channel, [])) == 0


async def test_coordinator_sequence_assigned() -> None:
    """The coordinator acquires a sequence > 0 on entry."""
    backend = InMemoryBackend()
    settings = _fast_settings()

    async with Coordinator(backend, settings=settings) as _result:
        assert settings.sequence > 0


# ---------------------------------------------------------------------------
# Ping/Pong message handling
# ---------------------------------------------------------------------------


async def test_higher_sequence_wins() -> None:
    """When two nodes compete, the one with the higher sequence wins."""
    registry = InMemoryBackend.create_registry()

    results: list[tuple[int, ElectionResult]] = []

    async def run_node() -> None:
        backend = InMemoryBackend(registry=registry)
        settings = _fast_settings()
        async with Coordinator(backend, settings=settings) as result:
            await result.round_complete.wait()
            results.append((settings.sequence, result))

    await asyncio.gather(run_node(), run_node())

    # The node with the highest sequence should be the winner.
    winner = max(results, key=lambda x: x[0])
    assert winner[1].winner is True
    assert sum(1 for _, r in results if r.winner) == 1


# ---------------------------------------------------------------------------
# Re-export shim tests
# ---------------------------------------------------------------------------


async def test_shim_election_imports() -> None:
    """Old import paths still work via re-export shims."""
    from notifelect.election import Coordinator as C, ElectionResult as ER, Settings as S

    assert C is Coordinator
    assert ER is ElectionResult
    assert S is Settings


async def test_shim_queries_imports() -> None:
    """Old import paths still work via re-export shims."""
    from notifelect.queries import Queries, SQLBuilder

    # Queries is aliased to PostgreSQLBackend
    assert Queries is PostgreSQLBackend
    assert SQLBuilder is not None


async def test_shim_task_manager_imports() -> None:
    """Old import paths still work via re-export shims."""
    from notifelect.core.task_manager import TaskManager as CoreTM
    from notifelect.task_manager import TaskManager

    assert TaskManager is CoreTM
