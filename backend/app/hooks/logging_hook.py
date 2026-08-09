"""Logging setup for the app's own logger.

Deliberately doesn't touch the root logger -- uvicorn owns that. We just
configure our named logger with a level from settings and keep httpx from
spamming INFO lines for every model call.
"""
from __future__ import annotations

import logging

from app.config import settings

logger = logging.getLogger("data_analyst_agent")

if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
    )
    logger.addHandler(_handler)
    logger.setLevel(settings.log_level.upper())
    logger.propagate = False

# httpx logs every request at INFO. Once per agent step is a lot of noise.
logging.getLogger("httpx").setLevel(logging.WARNING)


def log_step(node: str, message: str, *, status: str = "ok") -> None:
    level = logging.ERROR if status == "error" else logging.INFO
    logger.log(level, "[%s] %s", node, message)
