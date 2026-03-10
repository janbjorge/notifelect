from __future__ import annotations

import asyncio
import dataclasses
from datetime import timedelta

from notifelect import logconfig, models
from notifelect.core.messages import MessageFactory
from notifelect.core.settings import Settings
from notifelect.core.task_manager import TaskManager
from notifelect.ports import BackendPort


@dataclasses.dataclass
class ElectionResult:
    """Holds whether this node won the most recent election."""

    winner: bool = dataclasses.field(init=False, default=False)
    round_complete: asyncio.Event = dataclasses.field(
        default_factory=asyncio.Event,
        init=False,
    )


@dataclasses.dataclass
class ElectionRound:
    """Runs periodic election rounds, collecting ballots and picking a winner."""

    settings: Settings
    messages: MessageFactory

    ballots: list[models.MessageExchange] = dataclasses.field(
        default_factory=list,
        init=False,
    )
    result: ElectionResult = dataclasses.field(
        default_factory=ElectionResult,
        init=False,
    )
    shutdown_event: asyncio.Event = dataclasses.field(
        default_factory=asyncio.Event,
        init=False,
    )

    async def sleep_unless_shutdown(self, duration: timedelta) -> bool:
        """Sleep for *duration*. Returns True if time elapsed, False if shutdown was signalled."""
        try:
            await asyncio.wait_for(
                self.shutdown_event.wait(),
                timeout=duration.total_seconds(),
            )
            return False  # shutdown was signalled
        except asyncio.TimeoutError:
            return True  # time elapsed normally

    def shutdown(self) -> None:
        """Signal the election loop to stop."""
        self.shutdown_event.set()

    async def run(self, outbox: asyncio.Queue[models.MessageExchange]) -> None:
        """Election loop: ping, collect pongs, pick winner, repeat."""
        while not self.shutdown_event.is_set():
            if not await self.sleep_unless_shutdown(self.settings.election_interval):
                return

            logconfig.logger.debug("Election ping emitted")
            outbox.put_nowait(self.messages.ping())

            if not await self.sleep_unless_shutdown(self.settings.election_timeout):
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
            self.result.round_complete.set()


@dataclasses.dataclass
class Coordinator:
    """Bully-algorithm leader election over any pub/sub backend.

    The node with the highest sequence number wins. On entry the coordinator
    acquires a sequence from the backend, starts listening for messages,
    and runs periodic election rounds.

    Reference: https://www.cs.colostate.edu/~cs551/CourseNotes/Synchronization/BullyExample.html
    """

    backend: BackendPort

    settings: Settings = dataclasses.field(default_factory=Settings)

    tasks: TaskManager = dataclasses.field(
        default_factory=TaskManager,
        init=False,
    )
    round: ElectionRound = dataclasses.field(init=False)
    messages: MessageFactory = dataclasses.field(init=False)
    outbox: asyncio.Queue[models.MessageExchange] = dataclasses.field(
        default_factory=asyncio.Queue,
        init=False,
    )

    def __post_init__(self) -> None:
        self.messages = MessageFactory(
            self.settings,
            models.Channel(self.backend.channel),
        )
        self.round = ElectionRound(self.settings, self.messages)

    def handle_ping(self, ping: models.MessageExchange) -> None:
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
            self.outbox.put_nowait(self.messages.pong())

    def handle_pong(self, pong: models.MessageExchange) -> None:
        logconfig.logger.debug(
            "Pong received: message_id=%s, process_id=%s",
            pong.message_id,
            pong.process_id,
        )
        self.round.ballots.append(pong)

    def on_notification(self, *args: object) -> None:
        """Listener callback invoked by the backend adapter."""
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
            self.handle_ping(parsed)
        elif parsed.type == "Pong":
            self.handle_pong(parsed)
        else:
            logconfig.logger.error("Unknown message type: %s", parsed.type)
            raise NotImplementedError(parsed)

    async def outbox_worker(self) -> None:
        """Drain the outbox queue, sending messages one at a time."""
        while True:
            message = await self.outbox.get()
            try:
                await self.backend.publish(
                    self.backend.channel,
                    message.model_dump_json(),
                )
            except Exception:
                logconfig.logger.exception("Failed to send outbox message")

    async def __aenter__(self) -> ElectionResult:
        self.settings.sequence = models.Sequence(
            await self.backend.next_sequence(),
        )
        self.tasks.add(asyncio.create_task(self.outbox_worker()))
        self.tasks.add(asyncio.create_task(self.round.run(self.outbox)))
        await self.backend.subscribe(
            self.backend.channel,
            self.on_notification,
        )

        # Announce ourselves to trigger an immediate election.
        self.outbox.put_nowait(self.messages.ping())
        return self.round.result

    async def __aexit__(self, *_: object) -> None:
        # 1. Stop the election loop so no more pings are enqueued.
        self.round.shutdown()
        # 2. Send a zero-ping so the next-in-line can win quickly.
        self.outbox.put_nowait(self.messages.zero_ping())
        # 3. Cancel running tasks and wait for them to finish.
        for task in list(self.tasks.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks.tasks, return_exceptions=True)
        # 4. Remove listener so no more notifications enqueue pongs.
        await self.backend.unsubscribe(
            self.backend.channel,
            self.on_notification,
        )
        # 5. Drain any remaining outbox messages serially.
        while not self.outbox.empty():
            try:
                message = self.outbox.get_nowait()
                await self.backend.publish(
                    self.backend.channel,
                    message.model_dump_json(),
                )
            except Exception:
                logconfig.logger.exception("Failed to send remaining outbox message")
        # 6. Give the next-in-line a chance to win quickly.
        await self.backend.publish(
            self.backend.channel,
            self.messages.zero_ping().model_dump_json(),
        )
