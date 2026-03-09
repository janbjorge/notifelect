from __future__ import annotations

import asyncio
import dataclasses


@dataclasses.dataclass
class TaskManager:
    """Tracks a set of asyncio tasks and auto-removes them on completion."""

    tasks: set[asyncio.Task] = dataclasses.field(
        default_factory=set,
        init=False,
    )

    def add(self, task: asyncio.Task) -> None:
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def __aenter__(self) -> TaskManager:
        return self

    async def __aexit__(self, *_: object) -> None:
        await asyncio.gather(*self.tasks)
