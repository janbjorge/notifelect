from __future__ import annotations

import asyncio
import dataclasses
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

import asyncpg

from notifelect import logconfig, models, queries, tm


@dataclasses.dataclass
class Outcome:
    """
    Dataclass to represent the outcome of an election, storing the winner status as a boolean.
    """

    winner: bool = dataclasses.field(
        init=False,
        default=False,
    )


@dataclasses.dataclass
class Settings:
    """
    Dataclass to store settings for election processes,
    including namespace, interval, timeout, and identity details.
    """

    namespace: str = dataclasses.field(
        default="",
    )

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
class MessageCreator:
    """
    Responsible for creating messages used in election processes,
    utilizing provided settings and queries.
    """

    settings: Settings
    queries: queries.Queries

    def create_message(
        self,
        type: Literal["Ping", "Pong"],
        sequence: models.Sequence,
    ) -> models.MessageExchange:
        return models.MessageExchange(
            channel=self.queries.query_builder.channel,
            message_id=uuid.uuid4(),
            namespace=self.settings.namespace,
            process_id=self.settings.process_id,
            sent_at=datetime.now(tz=timezone.utc),
            sequence=sequence,
            type=type,
        )

    def pong(self) -> models.MessageExchange:
        """
        Creates a 'Pong' message using the create_message method with the type
        set to 'Pong'.
        """
        return self.create_message("Pong", self.settings.sequence)

    def ping(self) -> models.MessageExchange:
        """
        Creates a 'Ping' message using the create_message method with the type
        set to 'Ping'.
        """
        return self.create_message("Ping", self.settings.sequence)

    def zero_ping(self) -> models.MessageExchange:
        """
        PG sequence starts at one(1), emitting a zero(0) should ensure that
        there will be a real winner asap.
        """
        return self.create_message("Ping", models.Sequence(0))


@dataclasses.dataclass
class Electoral:
    """
    Manages the lifecycle of election events, tracking ballots,
    handling timeouts, and determining election outcomes.
    """

    settings: Settings
    queries: queries.Queries
    message_creator: MessageCreator

    ballots: list[models.MessageExchange] = dataclasses.field(
        default_factory=list,
        init=False,
    )
    outcome: Outcome = dataclasses.field(
        default_factory=Outcome,
        init=False,
    )
    alive: asyncio.Event = dataclasses.field(
        default_factory=asyncio.Event,
        init=False,
    )

    async def wait_for_event_or_timeout(
        self,
        timeout: timedelta,
    ) -> bool:
        """
        Waits for an event to occur or a timeout, returning True if the timeout occurred first.
        """

        event_task = asyncio.create_task(self.alive.wait())
        sleep_task = asyncio.create_task(asyncio.sleep(timeout.total_seconds()))
        done, pending = await asyncio.wait(
            [event_task, sleep_task], return_when=asyncio.FIRST_COMPLETED
        )

        for task in pending:
            task.cancel()

        return sleep_task in done

    async def routine_election(self) -> None:
        """
        Continuously runs the election process at intervals, initiating pings
        and collecting pong responses to determine the election winner based
        on message sequences.
        """
        while not self.alive.is_set():
            # Start an election
            timedout = await self.wait_for_event_or_timeout(
                self.settings.election_interval,
            )
            if not timedout:
                return
            logconfig.logger.debug("Election ping emitted")
            await self.queries.notify(self.message_creator.ping())

            # Wait for votes to come in.
            timedout = await self.wait_for_event_or_timeout(
                self.settings.election_timeout,
            )
            if not timedout:
                return

            # Pick winner.
            max_sequence = max(p.sequence for p in self.ballots)
            self.outcome.winner = max_sequence == self.settings.sequence
            self.ballots.clear()
            logconfig.logger.debug(
                "Election concluded, winner determined: %s (sequence: %s)",
                "me" if self.outcome.winner else "other",
                self.settings.sequence,
            )


@dataclasses.dataclass
class Coordinator:
    """
    Coordinates the election process in a distributed system using the bully algorithm,
    which is designed to ensure that the node with the highest ID
    (or sequence number in this context) always wins the election.

    Based on: https://www.cs.colostate.edu/~cs551/CourseNotes/Synchronization/BullyExample.html

    In the bully algorithm:
    - Each node can initiate an election process when it deems necessary
        (e.g., when a coordinator fails).
    - Upon initiating an election, the node sends a 'Ping' message to all nodes with higher IDs.
    - If a node receives a 'Ping', it responds with a 'Pong', asserting its
        candidacy for coordination.
    - The initiating node collects all 'Pong' responses and determines if it
        should continue its candidacy. If it receives a response from a higher ID, it will
        give up its candidacy and that node continues the election.
    - If no higher ID nodes respond, the initiating node declares itself as the coordinator.

    The election process uses asynchronous events to manage state transitions and
    timeouts, ensuring that the election completes even if not all nodes are responsive.
    """

    connection: asyncpg.Connection

    settings: Settings = dataclasses.field(
        default_factory=Settings,
    )

    tm: tm.TaskManager = dataclasses.field(
        default_factory=tm.TaskManager,
        init=False,
    )

    electoral: Electoral = dataclasses.field(
        init=False,
    )
    queries: queries.Queries = dataclasses.field(
        init=False,
    )
    message_creator: MessageCreator = dataclasses.field(
        init=False,
    )

    def __post_init__(self) -> None:
        """
        Initializes the queries object using the database connection, setting up the
        required database operations post dataclass instantiation.
        """
        self.queries = queries.Queries(self.connection)
        self.message_creator = MessageCreator(
            self.settings,
            self.queries,
        )
        self.electoral = Electoral(
            self.settings,
            self.queries,
            self.message_creator,
        )

    def handle_ping(self, ping: models.MessageExchange) -> None:
        """
        Processes a received 'Ping' message by checking the sequence and,
        if appropriate, emits a 'Pong' message in response.
        """
        logconfig.logger.debug(
            "Handling incoming Ping: message_id: %s, process_id: %s, sequence: %d",
            ping.message_id,
            ping.process_id,
            ping.sequence,
        )
        if self.settings.sequence >= ping.sequence:
            logconfig.logger.debug(
                "Responding with Pong: higher or equal sequence received; our: %d, incoming: %d",
                self.settings.sequence,
                ping.sequence,
            )
            assert self.settings.sequence > 0
            self.tm.add(
                asyncio.create_task(
                    self.queries.notify(
                        self.message_creator.pong(),
                    )
                ),
            )

    def handle_pong(self, pong: models.MessageExchange) -> None:
        """
        Handles a received 'Pong' message by adding it to the ballots
        for election processing.
        """
        logconfig.logger.debug(
            "Received Pong: message_id: %s, process_id: %s",
            pong.message_id,
            pong.process_id,
        )
        self.electoral.ballots.append(pong)

    def parse_and_dispatch(self, payload: str) -> None:
        """
        Parses incoming message payloads and dispatches them to the
        appropriate handler based on the message type, while performing
        necessary validation and error handling.
        """
        logconfig.logger.debug("Received payload: %s", payload)

        try:
            parsed = models.MessageExchange.model_validate_json(payload)
        except Exception:
            logconfig.logger.error("Failed to parse payload: %s", payload)
            return None

        logconfig.logger.debug(
            "Parsed message successfully: type: %s, namespace: %s",
            parsed.type,
            parsed.namespace,
        )

        if parsed.namespace != self.settings.namespace:
            logconfig.logger.warning(
                "Ignoring message due to namespace mismatch: expected: %s, received: %s",
                self.settings.namespace,
                parsed.namespace,
            )
            return None

        if parsed.type == "Ping":
            return self.handle_ping(parsed)

        if parsed.type == "Pong":
            return self.handle_pong(parsed)

        logconfig.logger.error(
            "Received unsupported message type: %s",
            parsed.type,
        )
        raise NotImplementedError(parsed)

    async def __aenter__(self) -> Outcome:
        """
        Asynchronous context manager entry point that starts the election
        process and sets up necessary listeners for incoming messages.
        """

        self.settings.sequence = await self.queries.sequence()
        self.tm.add(asyncio.create_task(self.electoral.routine_election()))
        await self.connection.add_listener(
            self.queries.query_builder.channel,
            lambda *x: self.parse_and_dispatch(x[-1]),
        )

        # Notify that there is a potential new sheriff in town.
        await self.queries.notify(self.message_creator.ping())
        return self.electoral.outcome

    async def __aexit__(self, *_: object) -> None:
        """
        Asynchronous context manager exit point that cleans up by removing
        listeners and completing any remaining tasks.
        """
        self.electoral.alive.set()
        await self.connection.remove_listener(
            self.queries.query_builder.channel,
            self.parse_and_dispatch,  # type: ignore[arg-type]
        )
        # Give `next in line` a chance to pick up quick.
        await self.queries.notify(self.message_creator.zero_ping())
        await asyncio.gather(*self.tm.tasks)
