from __future__ import annotations

from typing import Literal, NewType

from pydantic import UUID4, AwareDatetime, BaseModel

Channel = NewType(
    "Channel",
    str,
)

Namespace = NewType(
    "Namespace",
    str,
)

Sequence = NewType(
    "Sequence",
    int,
)


class MessageExchange(BaseModel):
    channel: Channel
    message_id: UUID4
    namespace: Namespace
    process_id: UUID4
    sent_at: AwareDatetime
    sequence: Sequence
    type: Literal["Ping", "Pong"]
