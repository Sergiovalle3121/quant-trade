"""Logging setup for CLI and batch jobs."""

from __future__ import annotations

import logging


def configure_logging(level: str = "INFO") -> None:
    """Configure concise structured-enough console logging."""
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
