# AGENTS.md - Notifelect

Distributed leader election library using PostgreSQL NOTIFY and the Bully algorithm.
Python 3.10+, asyncio-based, with asyncpg and Pydantic v2.

## Build & Environment

Package manager is **uv**. Build system is setuptools with setuptools-scm (version from git tags).

```bash
# Install in development mode with all dev dependencies
uv pip install -e ".[dev]"

# Or with plain pip
pip install -e ".[dev]"
```

## Lint & Type Check

CI runs all three checks independently -- all must pass:

```bash
ruff check .              # Linting (rules: C, E, F, I, PIE, Q, RET, RSE, SIM, W, C90)
ruff format . --check     # Formatting check (line-length = 100)
ruff format .             # Auto-format in place
mypy .                    # Type checking (strict: disallow_untyped_defs, pydantic plugin)
```

## Tests

Tests use **pytest** with **pytest-asyncio** (`asyncio_mode = "auto"`).
Tests require Docker (testcontainers spins up PostgreSQL 16).

```bash
# Run all tests (verbose, no capture -- matches CI)
pytest -vs

# Run a single test file
pytest -vs test/test_election.py

# Run a single test by name
pytest -vs -k "test_one_winner"

# Run a single parametrized variant
pytest -vs -k "test_one_winner[1]"
```

Test directory structure:
- `test/conftest.py` -- fixtures: PostgresContainer (session-scoped), schema install, connection factory
- `test/test_election.py` -- integration tests for election logic
- `test/test_tm.py` -- unit tests for TaskManager

## Code Style

### Imports

Every file starts with `from __future__ import annotations`, then three groups
separated by blank lines: stdlib, third-party, local. Enforced by ruff isort rules
with `combine-as-imports = true`.

```python
from __future__ import annotations

import asyncio
import dataclasses
from typing import Final

import asyncpg

from notifelect import logconfig, models, queries
```

Use `TYPE_CHECKING` guards for imports only needed by type annotations:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg
```

### Formatting

- Line length: **100** characters (ruff config)
- Formatter: **ruff format**
- Follow PEP 8; ruff enforces this automatically

### Type Annotations

All functions **must** have full parameter and return type annotations.
Enforced by mypy with `disallow_untyped_defs = true`.

Use `Final` for module-level constants, `NewType` for domain-specific type aliases,
and `Literal` for constrained string values.

```python
logger: Final = logging.getLogger("notifelect")
Channel = NewType("Channel", str)
type: Literal["Ping", "Pong"]
```

### Naming Conventions

- **Functions/methods**: `snake_case`
- **Classes**: `PascalCase`
- **Private members**: single underscore prefix `_method`, `_field`
- **Constants**: `Final` annotation with lowercase name (no ALL_CAPS)
- **Test parameters**: uppercase single letter for counts (e.g., `N`)

### Data Modeling

- **Pydantic `BaseModel`**: for wire-format / serialization models (JSON over PG NOTIFY)
- **`@dataclasses.dataclass`**: for everything else (config, internal state, utilities)
- Use `dataclasses.field()` with `init=False` for derived fields, `default_factory` for mutables
- Use `__post_init__` for wiring up dependencies that depend on constructor args

### Async Patterns

- Async context managers (`__aenter__`/`__aexit__`) for resource lifecycle
- `asyncio.Queue` for producer/consumer (outbox pattern)
- `asyncio.Event` for cooperative shutdown signalling
- `asyncio.Lock` for serializing database access
- `asyncio.wait_for` with `TimeoutError` for interruptible sleeps

### Error Handling

- No custom exception classes -- use broad `except Exception` with logging
- Use `logconfig.logger.error()` for errors, `.exception()` inside except blocks (includes traceback)
- Use `contextlib.suppress` for expected exceptions (e.g., `KeyboardInterrupt`)
- Raise `NotImplementedError` for unexpected/unhandled message types

### Logging

Single centralized logger in `logconfig.py`, accessed as `logconfig.logger` everywhere.
Level controlled by `LOGLEVEL` env var (default: INFO).

- Use **%-style formatting** (lazy evaluation), not f-strings:
  ```python
  logconfig.logger.debug("Ping received: process_id=%s, sequence=%d", pid, seq)
  ```
- `debug` for protocol flow, `warning` for recoverable issues, `error`/`exception` for failures

### Docstrings

Concise, imperative, single-sentence style. Not every method needs one --
rely on clear naming for simple methods. No formal convention (Google/NumPy/Sphinx).

```python
class Coordinator:
    """Bully-algorithm leader election over PostgreSQL NOTIFY/LISTEN."""

async def _sleep_unless_shutdown(self, duration: timedelta) -> bool:
    """Sleep for *duration*. Returns True if time elapsed, False if shutdown was signalled."""
```

### Comments

Sparse and purposeful -- explain *why*, not *what*. Use numbered step comments
for complex sequences. No TODOs, FIXMEs, or commented-out code.

### Git Commit Messages

- Present tense ("Add feature" not "Added feature")
- First line limited to 72 characters
- Reference issues and PRs after the first line

## Project Structure

```
notifelect/           # Package
  __init__.py         # Empty (no public re-exports)
  __main__.py         # CLI entry: python -m notifelect
  _version.py         # Auto-generated by setuptools-scm (gitignored)
  cli.py              # Argparse CLI (install/uninstall/listen)
  election.py         # Core election logic (Coordinator, ElectionRound, etc.)
  logconfig.py        # Centralized logging setup
  models.py           # Pydantic models, NewType aliases
  queries.py          # SQL builder + asyncpg query executor
  task_manager.py     # Asyncio task lifecycle utility
test/                 # Tests (outside package)
  conftest.py         # Shared fixtures
  test_election.py    # Integration tests
  test_tm.py          # Unit tests
tools/
  ex.py               # Example usage script
```

One concern per file. Empty `__init__.py` (no top-level re-exports).
Architecture follows ports-and-adapters pattern (see `ports-and-adapters.md`).

## CI

GitHub Actions (`.github/workflows/ci.yml`):
- **Linting job**: ruff check, ruff format --check, mypy (all run independently)
- **Test job**: pytest -vs across Python 3.10, 3.11, 3.12 on ubuntu-latest (5min timeout)
