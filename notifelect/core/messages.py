from __future__ import annotations

import dataclasses
import uuid
from datetime import datetime, timezone
from typing import Literal

from notifelect import models
from notifelect.core.settings import Settings


@dataclasses.dataclass
class MessageFactory:
    """Creates Ping/Pong messages for the election protocol."""

    settings: Settings
    channel: models.Channel

    def build(
        self,
        type: Literal["Ping", "Pong"],
        sequence: models.Sequence,
    ) -> models.MessageExchange:
        return models.MessageExchange(
            channel=self.channel,
            message_id=uuid.uuid4(),
            namespace=self.settings.namespace,
            process_id=self.settings.process_id,
            sent_at=datetime.now(tz=timezone.utc),
            sequence=sequence,
            type=type,
        )

    def pong(self) -> models.MessageExchange:
        return self.build("Pong", self.settings.sequence)

    def ping(self) -> models.MessageExchange:
        return self.build("Ping", self.settings.sequence)

    def zero_ping(self) -> models.MessageExchange:
        """Emit a sequence-0 ping to trigger an immediate re-election."""
        return self.build("Ping", models.Sequence(0))
