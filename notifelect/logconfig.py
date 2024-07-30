from __future__ import annotations

import logging
import os
from typing import Final

logging.basicConfig()
logger: Final = logging.getLogger("notifelect")
logger.setLevel(level=os.environ.get("LOGLEVEL", "INFO").upper())
