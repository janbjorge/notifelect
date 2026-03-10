from __future__ import annotations

import asyncio
import dataclasses


@dataclasses.dataclass
class TaskManager:
    tasks: set[asyncio.Task[None]] = dataclasses.field(default_factory=set, init=False)

    def add(self, task: asyncio.Task[None]) -> None:
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def __aenter__(self) -> TaskManager:
        return self

    async def __aexit__(self, *_: object) -> None:
        await asyncio.gather(*self.tasks)
