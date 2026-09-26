"""The owner's sales funnel: which posts bring visits, accounts and payments.

The owner publishes each text of the first-sales guide with its own tag
(``?ref=f4``). The first tag a browser arrives with is kept for
:data:`REF_DAYS` in a cookie that holds only the tag, and stored with the
account if one is created, so ``/panel`` can show, per day, language and tag:
visits, accounts, free first reports, free previews and paid reports.

Only tags listed in :data:`REF_TAGS` count; anything else is "directo", so a
stranger cannot fill the table with made-up tags. Visits are aggregate
counters (day, language, tag, count): no address and no user agent is
stored, and link previews and known robots are not counted. A browser counts
once a day (a ``rigor_seen`` cookie holds only the date), and the counters are
written by a background thread, never during a request. Everything
else is read from the tables the service already keeps. The page is for the
owner only, so it is in Spanish.
"""

from __future__ import annotations

import logging
import re
import threading
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

REF_COOKIE = "rigor_ref"
REF_DAYS = 30
#: Holds only the day a browser was last counted, so it counts once a day.
SEEN_COOKIE = "rigor_seen"
#: How often the in-memory visit counters are written to the database.
FLUSH_SECONDS = 60.0
DIRECT = "directo"
#: How far back /panel looks.
FUNNEL_DAYS = 30
MAX_REF_CHARS = 24
REF_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,23}")

#: Every tag the funnel counts, with what it stands for. The ids are the
#: templates of ``docs/AUDIT_LAUNCH_PLAYBOOK.md``; the rest are channels for
#: a link the owner posts in his own profile or bio.
REF_TAGS: dict[str, str] = {
    "p1": "P1 · mensaje a un conocido",
    "w0": "Estado de WhatsApp",
    "f1": "F1 · hilo comercial (Forex Factory)",
    "f2": "F2 · respuesta en un foro",
    "f3": "F3 · entrada de blog (XML de optimización)",
    "f4": "F4 · Sharpe por pura suerte",
    "f5": "F5 · antes de comprar un EA o copiar una señal",
    "f6": "F6 · antes de pagar un reto",
    "f7": "F7 · tabla mensual de un gestor o fondo",
    "f8": "F8 · fondo: efectivo, mercado y alfa",
    "f9": "F9 · el Sharpe en la moneda de tu cuenta",
    "f10": "F10 · Revolut o Zerodha",
    "f11": "F11 · cuenta protegida",
    "v1": "V1 · vendedor de EA",
    "d1": "D1 · trader de retos",
    "d2": "D2 · copiar o invertir con otro",
    "d3": "D3 · acciones, futuros o cripto",
    "d4": "D4 · fondos",
    "d5": "D5 · inversor particular en Europa",
    "mql5": "Perfil de MQL5",
    "rankia": "Perfil de Rankia",
    "reddit": "Perfil de Reddit",
    "ff": "Perfil de Forex Factory",
    "telegram": "Telegram",
    "youtube": "YouTube",
    "x": "X (Twitter)",
    "instagram": "Instagram",
    "facebook": "Facebook",
    "linkedin": "LinkedIn",
    "tiktok": "TikTok",
    "email": "Firma de correo",
}

#: Link previews and robots: they fetch a page without a person reading it.
_ROBOT = re.compile(
    r"bot|crawl|spider|slurp|preview|facebookexternalhit|whatsapp|telegram|discord|"
    r"skype|curl|wget|python|httpx|go-http|java/|headless|lighthouse|monitor",
    re.IGNORECASE,
)


def clean_ref(value: str | None) -> str:
    """A listed tag, lower-cased; ``""`` for a missing, malformed or unknown one."""
    tag = (value or "").strip().lower()[: MAX_REF_CHARS + 1]
    if not REF_PATTERN.fullmatch(tag):
        return ""
    return tag if tag in REF_TAGS else ""


def is_person(user_agent: str | None) -> bool:
    """``False`` for an empty user agent, a link preview or a known robot."""
    agent = user_agent or ""
    return bool(agent) and not _ROBOT.search(agent)


def day_of(value: str | datetime) -> str:
    """``YYYY-MM-DD`` of an ISO timestamp or a datetime, in UTC."""
    if isinstance(value, datetime):
        return value.astimezone(UTC).strftime("%Y-%m-%d")
    return value[:10]


def since_day(now: datetime, days: int = FUNNEL_DAYS) -> str:
    return day_of(now - timedelta(days=days - 1))


STAGES: tuple[str, ...] = ("visits", "signups", "welcome", "previews", "paid_code", "paid_card")

STAGE_LABELS: dict[str, str] = {
    "visits": "Visitas",
    "signups": "Cuentas",
    "welcome": "Informe gratis",
    "previews": "Vistas previas",
    "paid_code": "Pagos con código",
    "paid_card": "Pagos con tarjeta",
}


@dataclass
class FunnelCounts:
    """One stage count per :data:`STAGES` name."""

    counts: dict[str, int] = field(default_factory=lambda: dict.fromkeys(STAGES, 0))

    def add(self, stage: str, amount: int = 1) -> None:
        self.counts[stage] += amount

    @property
    def paid(self) -> int:
        return self.counts["paid_code"] + self.counts["paid_card"]


@dataclass
class Funnel:
    """Counts by ``(day, locale)`` and by tag over the last :data:`FUNNEL_DAYS`."""

    by_day: dict[tuple[str, str], FunnelCounts] = field(default_factory=dict)
    by_ref: dict[str, FunnelCounts] = field(default_factory=dict)
    total: FunnelCounts = field(default_factory=FunnelCounts)

    def add(self, stage: str, *, day: str, locale: str, ref: str, amount: int = 1) -> None:
        ref = ref if ref in REF_TAGS else DIRECT
        self.by_day.setdefault((day, locale), FunnelCounts()).add(stage, amount)
        self.by_ref.setdefault(ref, FunnelCounts()).add(stage, amount)
        self.total.add(stage, amount)


def build(events: dict[str, list[tuple[str, str, str, int]]]) -> Funnel:
    """A :class:`Funnel` from ``Store.funnel_events`` rows."""
    funnel = Funnel()
    for stage in STAGES:
        for day, locale, ref, count in events.get(stage, ()):
            funnel.add(stage, day=day, locale=locale, ref=ref, amount=count)
    return funnel


class VisitCounter:
    """Visits counted in memory and written to the database off the request path.

    A request only adds to a ``Counter`` under a lock; a daemon thread (like
    ``retention.RetentionWorker``) writes the totals every
    :data:`FLUSH_SECONDS`, and ``/panel`` flushes before it reads, so a slow
    database never holds up a page. Counts that fail to write are kept for
    the next flush.
    """

    def __init__(self, store: Any, *, interval_seconds: float = FLUSH_SECONDS) -> None:
        self._store = store
        self._interval = interval_seconds
        self._lock = threading.Lock()
        self._pending: Counter[tuple[str, str, str]] = Counter()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def add(self, *, day: str, locale: str, ref: str) -> None:
        with self._lock:
            self._pending[(day, locale[:8], ref[:MAX_REF_CHARS])] += 1

    def flush(self) -> None:
        with self._lock:
            batch, self._pending = self._pending, Counter()
        failed: Counter[tuple[str, str, str]] = Counter()
        for (day, locale, ref), amount in batch.items():
            try:
                self._store.count_visit(day=day, locale=locale, ref=ref, amount=amount)
            except Exception:  # noqa: BLE001 - kept for the next flush
                failed[(day, locale, ref)] += amount
        if failed:
            logger.warning("could not write %d visit counters; kept for later", len(failed))
            with self._lock:
                self._pending.update(failed)

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            self.flush()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="audit-visits", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None
        self.flush()


__all__ = [
    "DIRECT",
    "FLUSH_SECONDS",
    "FUNNEL_DAYS",
    "MAX_REF_CHARS",
    "REF_COOKIE",
    "REF_DAYS",
    "REF_TAGS",
    "SEEN_COOKIE",
    "STAGES",
    "STAGE_LABELS",
    "VisitCounter",
    "Funnel",
    "FunnelCounts",
    "build",
    "clean_ref",
    "day_of",
    "is_person",
    "since_day",
]
