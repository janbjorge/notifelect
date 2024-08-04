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
    winner: bool = dataclasses.field(
        init=False,
        default=False,
    )


@dataclasses.dataclass
class Settings:
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

    def create_pong(
        self,
        sequence: models.Sequence,
    ) -> models.MessageExchange:
        """
        Creates a 'Pong' message using the create_message method with the type
        set to 'Pong'.
        """
        return self.create_message("Pong", sequence)

    def create_ping(
        self,
        sequence: models.Sequence,
    ) -> models.MessageExchange:
        """
        Creates a 'Ping' message using the create_message method with the type
        set to 'Ping'.
        """
        return self.create_message("Ping", sequence)


@dataclasses.dataclass
class Coordinator:
    """
    Based on: https://www.cs.colostate.edu/~cs551/CourseNotes/Synchronization/BullyExample.html
    """

    connection: asyncpg.Connection
    ballots: list[models.MessageExchange] = dataclasses.field(
        default_factory=list,
        init=False,
    )

    outcome: Outcome = dataclasses.field(
        default_factory=Outcome,
        init=False,
    )

    tm: tm.TaskManager = dataclasses.field(
        default_factory=tm.TaskManager,
        init=False,
    )
    run_election: bool = dataclasses.field(
        default=True,
        init=False,
    )

    settings: Settings = dataclasses.field(
        default_factory=Settings,
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
        if self.sequence >= ping.sequence:
            logconfig.logger.debug(
                "Responding with Pong: higher or equal sequence received; our: %d, incoming: %d",
                self.sequence,
                ping.sequence,
            )
            self.tm.add(
                asyncio.create_task(
                    self.queries.notify(
                        self.message_creator.create_pong(self.sequence),
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
        self.ballots.append(pong)

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

    async def routine_election(self) -> None:
        """
        Continuously runs the election process at intervals, initiating pings
        and collecting pong responses to determine the election winner based
        on message sequences.
        """
        while self.run_election:
            # Start an election
            await asyncio.sleep(self.settings.election_interval.total_seconds())
            logconfig.logger.debug("Election ping emitted")
            await self.queries.notify(
                self.message_creator.create_ping(
                    self.sequence,
                )
            )

            # Wait for votes to come in.
            await asyncio.sleep(self.settings.election_timeout.total_seconds())

            # Pick winner.
            max_sequence = max(p.sequence for p in self.ballots)
            self.outcome.winner = max_sequence == self.sequence
            self.ballots.clear()
            logconfig.logger.debug(
                "Election concluded, winner determined: %s (sequence: %s)",
                "me" if self.outcome.winner else "other",
                self.sequence,
            )

    async def __aenter__(self) -> Outcome:
        """
        Asynchronous context manager entry point that starts the election
        process and sets up necessary listeners for incoming messages.
        """

        self.sequence = await self.queries.sequence()
        self.tm.add(asyncio.create_task(self.routine_election()))
        await self.connection.add_listener(
            self.queries.query_builder.channel,
            lambda *x: self.parse_and_dispatch(x[-1]),
        )
        await self.queries.notify(
            self.message_creator.create_ping(
                self.sequence,
            )
        )
        return self.outcome

    async def __aexit__(self, *_: object) -> None:
        """
        Asynchronous context manager exit point that cleans up by removing
        listeners and completing any remaining tasks.
        """
        self.run_election = False
        await self.connection.remove_listener(
            self.queries.query_builder.channel,
            self.parse_and_dispatch,  # type: ignore[arg-type]
        )
        # Give `next in line` a chance to pick up quick.
        await self.queries.notify(
            self.message_creator.create_ping(
                models.Sequence(0),
            )
        )
        await asyncio.gather(*self.tm.tasks)
