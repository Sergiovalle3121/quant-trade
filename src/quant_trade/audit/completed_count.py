"""A conservative public total, cached per app without reading audit payloads."""

from __future__ import annotations

import html
import logging
import threading
import time
from collections.abc import Callable, Collection, Sequence
from typing import Protocol

logger = logging.getLogger(__name__)

CACHE_SECONDS = 600.0
MIN_PUBLIC_COUNT = 25
COUNT_TEXT = {
    "es": "{n} backtests auditados",
    "en": "{n} backtests audited",
    "pt": "{n} backtests auditados",
}


class CompletedCountStore(Protocol):
    def count_completed_audits(self, *, excluded_ids: Sequence[str] = ()) -> int: ...


class CompletedAuditCounter:
    """One aggregate query per ten minutes, including unavailable results.

    A monotonic clock avoids wall-clock changes and the lock prevents parallel
    landing requests from repeating a refresh. A failed refresh hides the total
    until the next attempt: an unavailable count never becomes a displayed zero.
    """

    def __init__(
        self,
        store: CompletedCountStore,
        *,
        excluded_ids: Collection[str] = (),
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._store = store
        self._excluded_ids = tuple(sorted(set(excluded_ids)))
        self._clock = clock
        self._lock = threading.Lock()
        self._expires_at = float("-inf")
        self._total: int | None = None

    def get(self) -> int | None:
        with self._lock:
            now = self._clock()
            if now < self._expires_at:
                return self._total
            try:
                total = self._store.count_completed_audits(excluded_ids=self._excluded_ids)
                self._total = total if type(total) is int and total >= 0 else None
            except Exception:
                # The optional homepage count must not hide the upload form.
                # No exception text: a database error can contain private data.
                logger.warning("Public completed-audit count is unavailable")
                self._total = None
            self._expires_at = self._clock() + CACHE_SECONDS
            return self._total


def completed_count_html(total: int | None, locale: str = "es") -> str:
    """No markup below the threshold; every visible total is labelled measured."""
    if type(total) is not int or total < MIN_PUBLIC_COUNT:
        return ""
    text = COUNT_TEXT.get(locale, COUNT_TEXT["es"]).format(n=total)
    return (
        '<p class="completed-count" data-evidence="MEASURED">'
        f'{html.escape(text)} <span class="tag MEASURED">MEASURED</span></p>'
    )
