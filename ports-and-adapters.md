# Ports & Adapters

## Context

Notifelect implements distributed leader election using the Bully Algorithm.  The
algorithm itself needs exactly two infrastructure capabilities:

1. **Sequencing** — acquire a monotonically increasing number so nodes can compare rank.
2. **Pub/Sub** — broadcast messages to all participants and receive their responses.

Everything else (SQL, asyncpg, `pg_notify`, PG sequences) is adapter detail.  By
extracting these two capabilities into a single `BackendPort` protocol the election
logic becomes transport-agnostic: PostgreSQL today, Redis or NATS tomorrow, an
in-memory stub for unit tests.

### Coupling problems (before this change)

- `Coordinator.__post_init__` hardcoded `queries.Queries(self.connection)`.
- `Coordinator.connection` was typed as `asyncpg.Connection` — no abstraction.
- `MessageFactory` and `ElectionRound` were typed against concrete `queries.Queries`.
- LISTEN/UNLISTEN was hardcoded in `Coordinator` via `connection.add_listener` /
  `connection.remove_listener`, bypassing `Queries` entirely.
- `MessageFactory` depended on the full `Queries` object solely to read a channel name
  string.
- `SQLBuilder` read `os.environ["NOTIFELECT_PREFIX"]` at instantiation time.
- `Coordinator.__aexit__` reached into `self._round._shutdown.set()` — breaking
  encapsulation.
- The `Queries` class was simultaneously the interface and the PostgreSQL implementation.
- Zero `Protocol` classes existed in the codebase.

## Decision

Restructure Notifelect into a hexagonal architecture with a single `BackendPort`
protocol.  One protocol, one injection point.  Every backend implements one class.

### BackendPort

```python
class BackendPort(Protocol):
    @property
    def channel(self) -> str: ...

    async def next_sequence(self) -> int: ...
    async def publish(self, channel: str, payload: str) -> None: ...
    async def subscribe(self, channel: str, callback: Callable[..., Any]) -> None: ...
    async def unsubscribe(self, channel: str, callback: Callable[..., Any]) -> None: ...
    async def install(self) -> None: ...
    async def uninstall(self) -> None: ...
```

### How each backend maps

| BackendPort method | PostgreSQL (asyncpg) | Redis |
|--------------------|----------------------------------------------|-------------------------------|
| `channel`          | `SQLBuilder.channel` property                | Configured channel name       |
| `next_sequence()`  | `SELECT nextval('seq_notifelect')`           | `INCR notifelect:seq`         |
| `publish()`        | `SELECT pg_notify(channel, $1)`              | `PUBLISH channel payload`     |
| `subscribe()`      | `connection.add_listener(channel, callback)` | `SUBSCRIBE channel` + dispatch|
| `unsubscribe()`    | `connection.remove_listener(channel, cb)`    | `UNSUBSCRIBE channel`         |
| `install()`        | `CREATE SEQUENCE seq_notifelect`             | No-op (auto-created)          |
| `uninstall()`      | `DROP SEQUENCE seq_notifelect`               | `DEL notifelect:seq`          |

### Dependency injection

`Coordinator` takes a `BackendPort` instead of `asyncpg.Connection`:

```python
@dataclasses.dataclass
class Coordinator:
    backend: BackendPort
    settings: Settings = dataclasses.field(default_factory=Settings)
```

Users wrap their connection in the appropriate adapter:

```python
async with Coordinator(PostgreSQLBackend(conn), settings=settings) as result:
    ...
```

`MessageFactory` receives the channel name as a plain string — no dependency on
`Queries` or `SQLBuilder`.

### Encapsulation fix

`ElectionRound` now exposes a public `shutdown()` method.  `Coordinator.__aexit__`
calls `self._round.shutdown()` instead of reaching into the private `_shutdown` event.

### Backward compatibility

Re-export shims at old module paths preserve all existing imports:

```python
from notifelect.election import Coordinator, Settings, ElectionResult  # works
from notifelect.queries import Queries, SQLBuilder                     # works (Queries → PostgreSQLBackend)
from notifelect.task_manager import TaskManager                        # works
```

### Directory layout

```
src/notifelect/
  __init__.py                 # Public API exports
  ports.py                    # BackendPort protocol
  models.py                   # MessageExchange, Channel, Namespace, Sequence
  logconfig.py                # Logger configuration
  py.typed                    # PEP 561 marker

  core/
    __init__.py
    election.py               # Coordinator, ElectionRound, ElectionResult
    messages.py               # MessageFactory
    settings.py               # Settings
    task_manager.py           # TaskManager

  adapters/
    __init__.py
    postgresql.py             # PostgreSQLBackend, SQLBuilder (implements BackendPort)
    inmemory.py               # InMemoryBackend (for tests, implements BackendPort)

  # Re-export shims (backward compat)
  election.py                 # → core/election, core/messages, core/settings
  queries.py                  # → adapters/postgresql (Queries = PostgreSQLBackend)
  task_manager.py             # → core/task_manager

  cli.py                      # CLI entry point (PostgreSQL-specific)
  __main__.py                 # python -m notifelect
```

Import rule: `core/` imports only from `ports.py` and `models.py`.
`adapters/` imports from `ports.py` and `models.py`.  Nothing in `core/`
imports from `adapters/`.

### Test structure

- `test/test_postgresql_election.py` — integration tests against PostgreSQL via `PostgreSQLBackend`.
- `test/test_inmemory_election.py` — unit tests against `InMemoryBackend`: protocol
  conformance, single-node election, multi-node election, lifecycle cleanup, re-export
  shim verification.
- `test/test_tm.py` — `TaskManager` unit tests (no I/O).

## Consequences

### Positive

- The election core is transport-agnostic.  Adding Redis or NATS is one new file
  in `adapters/` implementing `BackendPort`.
- `Coordinator` and `ElectionRound` are unit-testable via `InMemoryBackend` — no
  PostgreSQL required.
- `BackendPort` documents exactly what the election needs: 7 members, no SQL.
- One protocol, one injection point: simple to understand and wire up.
- Re-export shims make the restructure invisible to existing users.
- `MessageFactory` no longer depends on `Queries` for a channel name string.
- `ElectionRound._shutdown` is no longer accessed cross-object.

### Negative

- Re-export shim files add maintenance overhead until a major version removes them.
- `BackendPort` must stay in sync with what the core actually calls.
- Adds structural complexity to a small codebase.

### Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| Breaking `from notifelect.election import Coordinator` | Re-export shim at old path; verified by tests |
| `BackendPort` grows too wide | Protocol has 7 members; additions require justification |
| `SQLBuilder` env-var coupling | Remains in the PG adapter only; not visible to the core |
| `logconfig.logger` singleton | Keep as-is; low-priority compared to transport abstraction |
