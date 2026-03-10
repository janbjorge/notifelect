# notifelect

Leader election for distributed Python services, built on PostgreSQL NOTIFY and the Bully algorithm.

If your stack already includes PostgreSQL, notifelect lets you add leader election without introducing Redis, ZooKeeper, etcd, or any other coordination service.

## When to use this

- You need exactly one worker to run a periodic job (cron-style scheduler, cache warmer, report generator).
- You want a primary node that owns a shared resource while others stand by.
- You run multiple replicas of a service and only one should consume from a queue at a time.
- You want graceful hand-off: when the leader exits cleanly, the next node takes over immediately.

## Requirements

- Python 3.10+
- PostgreSQL (any recent version)
- [asyncpg](https://github.com/MagicStack/asyncpg)

## Installation

```bash
pip install notifelect
```

Then create the required PostgreSQL sequence once, at deploy time:

```bash
python -m notifelect install --pg-dsn postgresql://user:pass@host/db
```

That's the only schema change notifelect makes: a single sequence used to assign monotonically increasing IDs to nodes.

## Quickstart

```python
import asyncio
import asyncpg
from notifelect import Coordinator, PostgreSQLBackend

async def main() -> None:
    conn = await asyncpg.connect("postgresql://user:pass@host/db")
    async with Coordinator(PostgreSQLBackend(conn)) as result:
        while True:
            if result.winner:
                print("I am the leader")
                # do leader work here
            await asyncio.sleep(5)

asyncio.run(main())
```

`result.winner` is a plain boolean that updates after each election round. There is no callback to register; just read the value whenever you need it.

## How it works

Each node fetches a unique sequence number from a PostgreSQL sequence on startup. Periodically, every node broadcasts a Ping over a PostgreSQL NOTIFY channel. Nodes with a lower sequence number respond with a Pong. After a short collection window, any node that received no Pong with a higher sequence than its own declares itself the winner.

This is the [Bully algorithm](https://en.wikipedia.org/wiki/Bully_algorithm): the node with the highest sequence number always wins.

When a node exits cleanly it broadcasts a zero-sequence Ping, letting the next-highest node win in the following round without waiting for a timeout.

## Configuration

```python
from datetime import timedelta
from notifelect import Coordinator, PostgreSQLBackend, Settings

settings = Settings(
    namespace="my-service",        # isolate this election group on the shared channel
    election_interval=timedelta(seconds=20),  # how often to run a round (default: 20s)
    election_timeout=timedelta(seconds=5),    # pong collection window (default: 5s)
)

async with Coordinator(PostgreSQLBackend(conn), settings=settings) as result:
    ...
```

**`namespace`** is useful when multiple independent services share the same PostgreSQL instance. Coordinators only react to messages within their own namespace, so elections don't interfere.

**`election_interval`** controls how quickly a new leader is elected after a failure. Lower values mean faster recovery but more database traffic. The full round cycle is `election_interval + election_timeout`.

## Running multiple nodes

Each node gets its own connection and `Coordinator`. Start as many as you like; exactly one will be the winner at any given time.

```python
import asyncio
import asyncpg
from notifelect import Coordinator, PostgreSQLBackend

async def run_node(dsn: str) -> None:
    conn = await asyncpg.connect(dsn)
    async with Coordinator(PostgreSQLBackend(conn)) as result:
        await asyncio.sleep(float("inf"))  # keep running

async def main() -> None:
    dsn = "postgresql://user:pass@host/db"
    await asyncio.gather(run_node(dsn), run_node(dsn), run_node(dsn))

asyncio.run(main())
```

In a real deployment each node runs in its own process or container and connects to the same PostgreSQL database.

## Database object naming

By default notifelect creates:

- Channel: `ch_notifelect`
- Sequence: `seq_notifelect`

Set the `NOTIFELECT_PREFIX` environment variable (or pass `--prefix` to the CLI) to namespace these objects:

```bash
NOTIFELECT_PREFIX=myapp_ python -m notifelect install --pg-dsn ...
# creates: myapp_ch_notifelect, myapp_seq_notifelect
```

Then pass the same prefix when constructing the backend:

```python
from notifelect import PostgreSQLBackend, SQLBuilder

backend = PostgreSQLBackend(conn, sql=SQLBuilder(
    channel="myapp_ch_notifelect",
    sequence_name="myapp_seq_notifelect",
))
```

## CLI reference

```bash
# Create the PostgreSQL sequence
python -m notifelect install [--dry-run] [connection flags]

# Drop the PostgreSQL sequence
python -m notifelect uninstall [--dry-run] [connection flags]

# Subscribe and print election messages (useful for debugging)
python -m notifelect listen [--channel CHANNEL] [connection flags]
```

Connection flags: `--pg-dsn`, `--pg-host`, `--pg-port`, `--pg-user`, `--pg-database`, `--pg-password`. All also read from the corresponding `PG*` environment variables.

`--dry-run` prints the SQL that would run without executing it.

## Custom backend

The `BackendPort` protocol lets you swap PostgreSQL for any pub/sub transport:

```python
from notifelect import BackendPort, Coordinator

class MyBackend:
    @property
    def channel(self) -> str: ...
    async def next_sequence(self) -> int: ...
    async def publish(self, channel: str, payload: str) -> None: ...
    async def subscribe(self, channel: str, callback) -> None: ...
    async def unsubscribe(self, channel: str, callback) -> None: ...
    async def install(self) -> None: ...
    async def uninstall(self) -> None: ...

async with Coordinator(MyBackend()) as result:
    ...
```

notifelect ships with an `InMemoryBackend` for tests that need multiple simulated nodes without a real database.

## Testing

notifelect ships with an `InMemoryBackend` that simulates the pub/sub bus in-process:

```python
from notifelect import Coordinator
from notifelect.adapters.inmemory import InMemoryBackend

async def test_single_winner() -> None:
    registry = InMemoryBackend.create_registry()
    backends = [InMemoryBackend(registry=registry) for _ in range(3)]

    async with (
        Coordinator(backends[0]) as r0,
        Coordinator(backends[1]) as r1,
        Coordinator(backends[2]) as r2,
    ):
        await asyncio.sleep(1)
        assert sum([r0.winner, r1.winner, r2.winner]) == 1
```

## Contributing

Clone the repository and install in development mode:

```bash
git clone https://github.com/janbjorge/notifelect
cd notifelect
uv sync --extra dev
```

Run the full check suite before submitting a pull request:

```bash
uv run ruff check .
uv run ruff format . --check
uv run mypy .
uv run pytest -vs
```

Tests require Docker; [testcontainers](https://testcontainers-python.readthedocs.io/) spins up a PostgreSQL 16 container automatically.

Please keep commits focused and write present-tense commit messages ("Add feature", not "Added feature"). Open an issue before starting large changes so we can align on direction.

## License

MIT
