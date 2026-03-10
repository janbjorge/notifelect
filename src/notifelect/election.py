"""Re-export shim — preserves ``from notifelect.election import ...``."""

from __future__ import annotations

from notifelect.core.election import Coordinator, ElectionResult, ElectionRound
from notifelect.core.messages import MessageFactory
from notifelect.core.settings import Settings

__all__ = [
    "Coordinator",
    "ElectionResult",
    "ElectionRound",
    "MessageFactory",
    "Settings",
]
