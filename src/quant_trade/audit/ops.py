"""Buffered, bounded private counters. Request paths never write telemetry to SQL."""

from __future__ import annotations

import logging
import math
import threading
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs

from quant_trade.audit.store_ops import BUCKETS_MS, OPERATIONS, OUTCOMES

logger = logging.getLogger(__name__)
MAX_PENDING_KEYS = 4096


class OpsCounter:
    def __init__(self, store: Any, *, interval_seconds: float = 60.0) -> None:
        self._store = store
        self._interval = interval_seconds
        self._lock = threading.Lock()
        self._flush_lock = threading.Lock()
        self._pending: Counter[tuple[str, str, str, str, int]] = Counter()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.dropped = 0
        self.flush_failed = False

    def observe(
        self,
        operation: str,
        outcome: str,
        seconds: float,
        *,
        locale: str = "es",
        at: datetime | None = None,
    ) -> None:
        try:
            self._observe(operation, outcome, seconds, locale=locale, at=at)
        except Exception:
            # Metrics are optional even if their in-memory buffer is unavailable.
            logger.warning("operations counter could not be buffered")

    def _observe(
        self,
        operation: str,
        outcome: str,
        seconds: float,
        *,
        locale: str,
        at: datetime | None,
    ) -> None:
        if operation not in OPERATIONS or outcome not in OUTCOMES or not math.isfinite(seconds):
            return
        ms = max(0, seconds) * 1000
        bucket = next((n for n in BUCKETS_MS if ms <= n), BUCKETS_MS[-1])
        day = (at or datetime.now(UTC)).astimezone(UTC).date().isoformat()
        key = (day, locale if locale in ("es", "en", "pt") else "es", operation, outcome, bucket)
        with self._lock:
            if key not in self._pending and len(self._pending) >= MAX_PENDING_KEYS:
                self.dropped += 1
            else:
                self._pending[key] += 1

    def flush(self) -> None:
        try:
            self._flush()
        except Exception:
            self.flush_failed = True
            logger.warning("operations flush unavailable")

    def _flush(self) -> None:
        # The worker and a panel read can flush together; serialize so retrying
        # a failed write cannot count a completed batch twice.
        # A panel read must not wait behind a worker whose database is unavailable.
        if not self._flush_lock.acquire(blocking=False):
            return
        try:
            with self._lock:
                batch, self._pending = self._pending, Counter()
            failed: Counter[tuple[str, str, str, str, int]] = Counter()
            for (day, locale, operation, outcome, bucket), count in batch.items():
                try:
                    self._store.count_ops(
                        day=day,
                        locale=locale,
                        operation=operation,
                        outcome=outcome,
                        bucket_ms=bucket,
                        amount=count,
                    )
                except Exception:  # telemetry must never change a customer's result
                    failed[(day, locale, operation, outcome, bucket)] += count
            self.flush_failed = bool(failed)
            with self._lock:
                for key, count in failed.items():
                    if key in self._pending or len(self._pending) < MAX_PENDING_KEYS:
                        self._pending[key] += count
                    else:
                        self.dropped += count
            if failed:
                logger.warning("operations counters could not be persisted; retry pending")
        finally:
            self._flush_lock.release()

    def start(self) -> None:
        if self._thread is not None:
            return

        def loop() -> None:
            while not self._stop.wait(self._interval):
                self.flush()
            self.flush()

        self._thread = threading.Thread(target=loop, name="audit-ops", daemon=True)
        try:
            self._thread.start()
        except Exception:
            self._thread = None
            self.flush_failed = True
            logger.warning("operations worker unavailable")

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        # Final persistence belongs to a daemon, never the lifespan caller. A
        # stuck database operation may outlive this budget without blocking restart.
        if self._thread is None:
            self._thread = threading.Thread(target=self.flush, name="audit-ops-close", daemon=True)
            try:
                self._thread.start()
            except Exception:
                self._thread = None
                self.flush_failed = True
                logger.warning("operations shutdown persistence unavailable")
                return
        self._thread.join(max(0.0, timeout))
        if not self._thread.is_alive():
            self._thread = None
        else:
            self.flush_failed = True
            logger.warning("operations shutdown persistence exceeded time budget")


class OpsMiddleware:
    """One upload/PDF request outcome, including rejections before multipart parsing."""

    def __init__(self, app: Any, *, counter: OpsCounter) -> None:
        self.app, self.counter = app, counter

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        path, method = scope.get("path", ""), scope.get("method", "")
        operation = "upload" if path == "/audits" and method == "POST" else ""
        parts = path.strip("/").split("/")
        if method == "GET" and (
            (len(parts) == 3 and parts[0] == "audits" and parts[2] == "pdf")
            or path in ("/ejemplo.pdf", "/sample.pdf", "/pt/exemplo.pdf")
        ):
            operation = "pdf"
        if scope.get("type") != "http" or not operation:
            await self.app(scope, receive, send)
            return
        started, status = time.monotonic(), 500

        async def tracked(message: Any) -> None:
            nonlocal status
            if message.get("type") == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, tracked)
        finally:
            outcome = (
                "success"
                if status < 400
                else "invalid"
                if status in (400, 408, 413, 422)
                else "busy"
                if status in (429, 503)
                else "error"
                if status >= 500
                else "denied"
            )
            query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
            default_locale = (
                "pt" if path == "/pt/exemplo.pdf" else "en" if path == "/sample.pdf" else "es"
            )
            locale = (
                scope.get("state", {}).get("ops_locale") or query.get("lang", [default_locale])[0]
            )
            # No request path, query, token or exception text enters a counter.
            try:
                self.counter.observe(operation, outcome, time.monotonic() - started, locale=locale)
            except Exception:
                logger.warning("operations request counter unavailable")


def percentile_bucket(rows: list[dict[str, Any]], q: float) -> str:
    counts: Counter[int] = Counter()
    for row in rows:
        counts[int(row["bucket_ms"])] += int(row["count"])
    target, seen = math.ceil(sum(counts.values()) * q), 0
    if not target:
        return "NOT_MEASURED"
    for bucket, amount in sorted(counts.items()):
        seen += amount
        if seen >= target:
            return ">120 s" if bucket == BUCKETS_MS[-1] else f"≤{bucket / 1000:g} s"
    return "NOT_MEASURED"


RETENTION_OVERDUE = timedelta(hours=36)


def _stored_utc(value: Any) -> datetime | None:
    """A stored stamp as UTC; naive text is UTC (``stamp`` writes UTC), unreadable is absent."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def retention_status(
    row: dict[str, Any] | None,
    *,
    enabled: bool,
    at: datetime,
    since: datetime | None = None,
) -> str:
    """``since`` is when this process began expecting a purge (its start).

    With no readable success for more than 36 h after it, the job is overdue,
    not unmeasured: a health write that always fails cannot hide forever.
    """
    if not enabled:
        return "disabled"
    row, now = row or {}, at.astimezone(UTC)
    success = _stored_utc(row.get("last_success_at"))
    if success is None:
        if since is not None and now - since.astimezone(UTC) > RETENTION_OVERDUE:
            return "overdue"
        return "failed" if row.get("error_code") else "not_measured"
    if now - success > RETENTION_OVERDUE:
        return "overdue"
    return "failed" if row.get("error_code") else "ok"
