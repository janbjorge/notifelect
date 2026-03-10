from __future__ import annotations

import dataclasses
import uuid
from datetime import timedelta

from notifelect import models


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
