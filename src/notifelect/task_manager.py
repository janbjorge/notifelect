"""Re-export shim — preserves ``from notifelect.task_manager import ...``."""

from __future__ import annotations

from notifelect.core.task_manager import TaskManager

__all__ = [
    "TaskManager",
]
