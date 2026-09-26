"""The owner's sales funnel: which posts bring visits, accounts and payments.

The owner publishes each text of the first-sales guide with its own tag
(``?ref=f4``). The first tag a browser arrives with is kept for
:data:`REF_DAYS` in a cookie that holds only the tag, and stored with the
account if one is created, so ``/panel`` can show, per day, language and tag:
visits, accounts, free first reports, free previews and paid reports.

Only tags listed in :data:`REF_TAGS` count; anything else is "directo", so a
stranger cannot fill the table with made-up tags. Visits are aggregate
counters (day, language, tag, count): no address, no cookie and no user agent
is stored, and link previews and known robots are not counted. Everything
else is read from the tables the service already keeps. The page is for the
owner only, so it is in Spanish.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

REF_COOKIE = "rigor_ref"
REF_DAYS = 30
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


__all__ = [
    "DIRECT",
    "FUNNEL_DAYS",
    "MAX_REF_CHARS",
    "REF_COOKIE",
    "REF_DAYS",
    "REF_TAGS",
    "STAGES",
    "STAGE_LABELS",
    "Funnel",
    "FunnelCounts",
    "build",
    "clean_ref",
    "day_of",
    "is_person",
    "since_day",
]
