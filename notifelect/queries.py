"""Re-export shim — preserves ``from notifelect.queries import ...``."""

from __future__ import annotations

from notifelect.adapters.postgresql import PostgreSQLBackend as Queries, SQLBuilder, with_prefix

__all__ = [
    "Queries",
    "SQLBuilder",
    "with_prefix",
]
