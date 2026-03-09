from __future__ import annotations

import asyncio
import dataclasses
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

import asyncpg

from notifelect import logconfig, models, queries, task_manager


@dataclasses.dataclass
class ElectionResult:
    """Holds whether this node won the most recent election."""

    winner: bool = dataclasses.field(init=False, default=False)


@dataclasses.dataclass
class Settings:
    """Configuration for the election process."""

    namespace: str = dataclasses.field(default="")

    election_interval: timedelta = dataclasses.field(
        default=timedelta(seconds=20),
    )
    election_timeout: timedelta = dataclasses.field(
        default=timedelta(seconds=5),
    )

    process_id: uuid.UUID = dataclasses.field(
        default_factory=uuid.uuid4,
        init=False,
    )
    sequence: models.Sequence = dataclasses.field(
        default=models.Sequence(0),
        init=False,
    )


@dataclasses.dataclass
class MessageFactory:
    """Creates Ping/Pong messages for the election protocol."""

    settings: Settings
    _queries: queries.Queries

    def _build(
        self,
        type: Literal["Ping", "Pong"],
        sequence: models.Sequence,
    ) -> models.MessageExchange:
        return models.MessageExchange(
            channel=self._queries.sql.channel,
            message_id=uuid.uuid4(),
            namespace=self.settings.namespace,
            process_id=self.settings.process_id,
            sent_at=datetime.now(tz=timezone.utc),
            sequence=sequence,
            type=type,
        )

    def pong(self) -> models.MessageExchange:
        return self._build("Pong", self.settings.sequence)

    def ping(self) -> models.MessageExchange:
        return self._build("Ping", self.settings.sequence)

    def zero_ping(self) -> models.MessageExchange:
        """Emit a sequence-0 ping to trigger an immediate re-election."""
        return self._build("Ping", models.Sequence(0))


@dataclasses.dataclass
class ElectionRound:
    """Runs periodic election rounds, collecting ballots and picking a winner."""

    settings: Settings
    _queries: queries.Queries
    _messages: MessageFactory

    ballots: list[models.MessageExchange] = dataclasses.field(
        default_factory=list,
        init=False,
    )
    result: ElectionResult = dataclasses.field(
        default_factory=ElectionResult,
        init=False,
    )
    _shutdown: asyncio.Event = dataclasses.field(
        default_factory=asyncio.Event,
        init=False,
    )

    async def _sleep_unless_shutdown(self, duration: timedelta) -> bool:
        """Sleep for *duration*. Returns True if time elapsed, False if shutdown was signalled."""
        try:
            await asyncio.wait_for(
                self._shutdown.wait(),
                timeout=duration.total_seconds(),
            )
            return False  # shutdown was signalled
        except asyncio.TimeoutError:
            return True  # time elapsed normally

    async def run(self, outbox: asyncio.Queue[models.MessageExchange]) -> None:
        """Election loop: ping, collect pongs, pick winner, repeat."""
        while not self._shutdown.is_set():
            if not await self._sleep_unless_shutdown(self.settings.election_interval):
                return

            logconfig.logger.debug("Election ping emitted")
            outbox.put_nowait(self._messages.ping())

            if not await self._sleep_unless_shutdown(self.settings.election_timeout):
                return

            if self.ballots:
                max_sequence = max(p.sequence for p in self.ballots)
                self.result.winner = max_sequence == self.settings.sequence
            else:
                # No responses: we are alone, so we win by default.
                self.result.winner = True

            self.ballots.clear()
            logconfig.logger.debug(
                "Election concluded: %s (sequence: %s)",
                "winner" if self.result.winner else "not winner",
                self.settings.sequence,
            )


@dataclasses.dataclass
class Coordinator:
    """Bully-algorithm leader election over PostgreSQL NOTIFY/LISTEN.

    The node with the highest sequence number wins. On entry the coordinator
    acquires a sequence from a PG sequence, starts listening for messages,
    and runs periodic election rounds.

    Reference: https://www.cs.colostate.edu/~cs551/CourseNotes/Synchronization/BullyExample.html
    """

    connection: asyncpg.Connection

    settings: Settings = dataclasses.field(default_factory=Settings)

    _tasks: task_manager.TaskManager = dataclasses.field(
        default_factory=task_manager.TaskManager,
        init=False,
    )
    _round: ElectionRound = dataclasses.field(init=False)
    _queries: queries.Queries = dataclasses.field(init=False)
    _messages: MessageFactory = dataclasses.field(init=False)
    _outbox: asyncio.Queue[models.MessageExchange] = dataclasses.field(
        default_factory=asyncio.Queue,
        init=False,
    )

    def __post_init__(self) -> None:
        self._queries = queries.Queries(self.connection)
        self._messages = MessageFactory(self.settings, self._queries)
        self._round = ElectionRound(self.settings, self._queries, self._messages)

    def _handle_ping(self, ping: models.MessageExchange) -> None:
        logconfig.logger.debug(
            "Ping received: message_id=%s, process_id=%s, sequence=%d",
            ping.message_id,
            ping.process_id,
            ping.sequence,
        )
        if self.settings.sequence <= 0:
            logconfig.logger.warning(
                "Ignoring ping: own sequence not yet assigned (sequence=%d)",
                self.settings.sequence,
            )
            return

        if self.settings.sequence >= ping.sequence:
            logconfig.logger.debug(
                "Responding with pong: ours=%d >= incoming=%d",
                self.settings.sequence,
                ping.sequence,
            )
            self._outbox.put_nowait(self._messages.pong())

    def _handle_pong(self, pong: models.MessageExchange) -> None:
        logconfig.logger.debug(
            "Pong received: message_id=%s, process_id=%s",
            pong.message_id,
            pong.process_id,
        )
        self._round.ballots.append(pong)

    def _on_notification(self, *args: object) -> None:
        """Listener callback registered with asyncpg."""
        payload = str(args[-1])
        logconfig.logger.debug("Notification payload: %s", payload)

        try:
            parsed = models.MessageExchange.model_validate_json(payload)
        except Exception:
            logconfig.logger.error("Failed to parse payload: %s", payload)
            return

        if parsed.namespace != self.settings.namespace:
            logconfig.logger.debug(
                "Namespace mismatch: expected=%s, got=%s",
                self.settings.namespace,
                parsed.namespace,
            )
            return

        if parsed.type == "Ping":
            self._handle_ping(parsed)
        elif parsed.type == "Pong":
            self._handle_pong(parsed)
        else:
            logconfig.logger.error("Unknown message type: %s", parsed.type)
            raise NotImplementedError(parsed)

    async def _outbox_worker(self) -> None:
        """Drain the outbox queue, sending messages one at a time."""
        while True:
            message = await self._outbox.get()
            try:
                await self._queries.notify(message)
            except Exception:
                logconfig.logger.exception("Failed to send outbox message")

    async def __aenter__(self) -> ElectionResult:
        self.settings.sequence = await self._queries.next_sequence()
        self._tasks.add(asyncio.create_task(self._outbox_worker()))
        self._tasks.add(asyncio.create_task(self._round.run(self._outbox)))
        await self.connection.add_listener(
            self._queries.sql.channel,
            self._on_notification,
        )

        # Announce ourselves to trigger an immediate election.
        self._outbox.put_nowait(self._messages.ping())
        return self._round.result

    async def __aexit__(self, *_: object) -> None:
        # 1. Stop the election loop so no more pings are enqueued.
        self._round._shutdown.set()
        # 2. Signal the outbox worker to finish: enqueue a None sentinel
        #    and wait for it to drain.  Then cancel remaining tasks.
        self._outbox.put_nowait(self._messages.zero_ping())
        # 3. Remove listener so no more notifications enqueue pongs.
        #    Wait briefly for in-flight outbox sends to complete.
        for task in list(self._tasks.tasks):
            task.cancel()
        await asyncio.gather(*self._tasks.tasks, return_exceptions=True)
        await self.connection.remove_listener(
            self._queries.sql.channel,
            self._on_notification,
        )
        # 4. Drain any remaining outbox messages serially.
        while not self._outbox.empty():
            try:
                message = self._outbox.get_nowait()
                await self._queries.notify(message)
            except Exception:
                logconfig.logger.exception("Failed to send remaining outbox message")
        # Give the next-in-line a chance to win quickly.
        await self._queries.notify(self._messages.zero_ping())
