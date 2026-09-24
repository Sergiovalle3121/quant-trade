"""The retention purge, run by the web service itself.

The privacy page promises that unpaid uploads are deleted after
``AUDIT_RETENTION_DAYS``. A promise that depends on someone remembering a
cron job is fragile, so with ``AUDIT_AUTO_PURGE=true`` the service runs the
same purge as ``quant-trade audit purge --yes`` once at startup and then
every ``interval_seconds``. Setting that variable is the owner's explicit
confirmation of the retention delete (AGENTS.md, Phase 16); without it
nothing is deleted automatically and the CLI remains the way to purge.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

DAY_SECONDS = 24 * 60 * 60


def run_retention(store: Any, *, retention_days: int, now: datetime | None = None) -> int:
    """One purge run; returns how many unpaid audits were purged."""
    at = now or datetime.now(UTC)
    count = int(store.purge_expired(at, retention_days=retention_days))
    logger.info("retention purge: %d audit(s) older than %d day(s)", count, retention_days)
    return count


class RetentionWorker:
    """A daemon thread that purges at start and then on a fixed interval."""

    def __init__(
        self,
        store: Any,
        *,
        retention_days: int,
        interval_seconds: float = DAY_SECONDS,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._retention_days = retention_days
        self._interval = interval_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.runs = 0

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                run_retention(self._store, retention_days=self._retention_days, now=self._clock())
            except Exception:  # a failed run must not kill the service; retry next interval
                logger.exception("retention purge failed")
            self.runs += 1
            self._stop.wait(self._interval)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="audit-retention", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None


__all__ = ["DAY_SECONDS", "RetentionWorker", "run_retention"]
