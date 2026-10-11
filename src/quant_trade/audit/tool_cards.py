"""Static, memory-only social cards for the public research tools.

The finite catalogue names pages, never a visitor's inputs or results. Firm
names come from the same catalogue as the challenge pages, without logos or
endorsements. Rendering uses trusted inline SVG only: no database, network,
file reads or file writes. Missing Cairo remains an optional rendering failure
so the route can serve the site's default social image.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from threading import Lock
from types import MappingProxyType

from quant_trade.audit import raster
from quant_trade.audit.challenge_calc import FIRMS
from quant_trade.audit.guard import find_claims

CARD_SIZE = (1200, 630)
TOOL_KINDS = ("calculadora-reto", "calculadora-ruina", "reglas-prop-firm")
_LOCALES = ("es", "en", "pt")
# Freeze the finite catalogue used by validation and rendering together.
_FIRM_NAMES = MappingProxyType(dict(FIRMS))
_INK = "#202c36"
_MUTED = "#4c5b67"
_ACCENT = "#245d85"


@dataclass(frozen=True)
class _CardText:
    title: tuple[str, str]
    detail: str


_COPY: dict[str, dict[str, _CardText]] = {
    "es": {
        "calculadora-reto": _CardText(
            ("Calculadora de reto", "de prop firm"),
            "{count} firmas, reglas con fuente y fecha",
        ),
        "calculadora-ruina": _CardText(
            ("Calculadora de", "riesgo de ruina"),
            "Riesgo, rachas y límites del modelo",
        ),
        "reglas-prop-firm": _CardText(
            ("Tabla de reglas", "de prop firm"),
            "{count} firmas, límites, fuentes y fechas",
        ),
    },
    "en": {
        "calculadora-reto": _CardText(
            ("Prop firm challenge", "calculator"),
            "{count} firms, rules with sources and dates",
        ),
        "calculadora-ruina": _CardText(
            ("Risk of ruin", "calculator"),
            "Risk, streaks and model limitations",
        ),
        "reglas-prop-firm": _CardText(
            ("Prop firm", "rules table"),
            "{count} firms, limits, sources and dates",
        ),
    },
    "pt": {
        "calculadora-reto": _CardText(
            ("Calculadora de desafio", "de prop firm"),
            "{count} empresas, regras com fonte e data",
        ),
        "calculadora-ruina": _CardText(
            ("Calculadora de", "risco de ruína"),
            "Risco, sequências e limites do modelo",
        ),
        "reglas-prop-firm": _CardText(
            ("Tabela de regras", "de prop firm"),
            "{count} empresas, limites, fontes e datas",
        ),
    },
}
_TOOLS = {"es": "HERRAMIENTAS", "en": "RESEARCH TOOLS", "pt": "FERRAMENTAS"}
_FIRM_DETAIL = {
    "es": "Reglas con fuente y fecha",
    "en": "Rules with sources and dates",
    "pt": "Regras com fonte e data",
}
_UNAFFILIATED = {
    "es": "Rigor no está afiliado",
    "en": "Rigor is not affiliated",
    "pt": "A Rigor não é afiliada",
}
_MODEL_NOTE = {
    "es": "Herramienta de investigación · No es una predicción",
    "en": "Research tool · Not a forecast",
    "pt": "Ferramenta de pesquisa · Não é uma previsão",
}
_RULES_NOTE = {
    "es": "Consulta las reglas vigentes de cada firma",
    "en": "Consult each firm's current rules",
    "pt": "Consulte as regras vigentes de cada empresa",
}


def _validate(kind: str, locale: str, firm: str) -> None:
    if kind not in TOOL_KINDS:
        raise ValueError("unknown tool card")
    if locale not in _LOCALES:
        raise ValueError("locale must be es, en or pt")
    if firm and (kind != "calculadora-reto" or firm not in _FIRM_NAMES):
        raise ValueError("firm must name a published challenge page")


def tool_image_path(kind: str, locale: str, firm: str = "") -> str:
    """The stable image URL; only published tools, languages and firms exist."""
    _validate(kind, locale, firm)
    prefix = "" if locale == "es" else f"/{locale}"
    suffix = f"-{firm}" if firm else ""
    return f"{prefix}/og/{kind}{suffix}.png"


def tool_card_svg(kind: str, locale: str, firm: str = "") -> str:
    """A guarded, accessible 1200x630 SVG describing one published tool page.

    Cards describe the tool and its limitations, with no computed outcomes.
    Every visible and accessible text is checked by the profit-claim guard.
    """
    _validate(kind, locale, firm)
    words = _COPY[locale][kind]
    title = " ".join(words.title)
    detail = words.detail.format(count=len(_FIRM_NAMES))
    note = (_RULES_NOTE if kind == "reglas-prop-firm" else _MODEL_NOTE)[locale]
    summary = f"{title} · {detail}"
    if firm:
        detail = _FIRM_DETAIL[locale]
        summary = f"{title} · {_FIRM_NAMES[firm]} · {detail}"
    affiliation = _UNAFFILIATED[locale] if firm else ""
    description = " · ".join(part for part in (summary, affiliation, note) if part)
    shown = [summary, description]
    width, height = CARD_SIZE
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        'aria-labelledby="tool-card-title tool-card-desc" '
        f'xml:lang="{locale}">',
        f'<title id="tool-card-title">{html.escape(summary)}</title>',
        f'<desc id="tool-card-desc">{html.escape(description)}</desc>',
        f'<rect width="{width}" height="{height}" fill="#f7f6f2"/>',
        f'<rect width="8" height="{height}" fill="{_ACCENT}"/>',
        '<path d="M64 116H1136 M64 522H1136" stroke="#d6dde0" stroke-width="2"/>',
    ]

    def text(
        x: int,
        y: int,
        content: str,
        size: int,
        color: str = _INK,
        *,
        bold: bool = False,
        anchor: str = "start",
    ) -> None:
        shown.append(content)
        weight = "700" if bold else "400"
        parts.append(
            f'<text x="{x}" y="{y}" font-family="Arial, sans-serif" font-size="{size}" '
            f'font-weight="{weight}" fill="{color}" text-anchor="{anchor}">'
            f"{html.escape(content)}</text>"
        )

    text(64, 78, "RIGOR", 34, _ACCENT, bold=True)
    text(1136, 76, _TOOLS[locale], 17, _MUTED, anchor="end")
    for index, line in enumerate(words.title):
        text(64, 215 + 65 * index, line, 51, bold=True)
    if firm:
        text(64, 351, _FIRM_NAMES[firm], 38, _ACCENT, bold=True)
        text(64, 398, detail, 26, _MUTED)
        text(64, 476, affiliation, 23, _MUTED)
    else:
        text(64, 351, detail, 28, _MUTED)
        parts.append(f'<path d="M64 402H144" stroke="{_ACCENT}" stroke-width="5"/>')

    # A neutral document motif: no firm marks, charts or illustrative results.
    parts += [
        '<g aria-hidden="true">',
        '<rect x="916" y="182" width="220" height="268" rx="16" '
        'fill="#ffffff" stroke="#d6dde0" stroke-width="2"/>',
        f'<rect x="943" y="211" width="52" height="7" rx="3" fill="{_ACCENT}"/>',
        '<path d="M943 243H1108" stroke="#d6dde0" stroke-width="2"/>',
    ]
    for y in (270, 326, 382):
        parts += [
            f'<rect x="943" y="{y}" width="26" height="26" rx="5" fill="#e8eef2"/>',
            f'<path d="M986 {y + 7}H1108 M986 {y + 20}H1075" '
            'stroke="#9baab5" stroke-width="4" stroke-linecap="round"/>',
        ]
    parts.append("</g>")
    text(64, 574, note, 21, _MUTED)
    text(1136, 574, "rigorscore.com", 22, _ACCENT, anchor="end")
    parts.append("</svg>")
    if find_claims(" ".join(shown)):
        raise ValueError("tool card text contains unsupported wording")
    return "".join(parts)


class ToolPNGCache:
    """Cache only successful renders from the finite published catalogue.

    At most three languages times (three tools plus the firm pages) can be
    retained. A lock makes concurrent first requests share one render. Failure
    is never cached, so installing or restoring Cairo needs no cache reset.
    """

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str, str], bytes] = {}
        self._lock = Lock()

    def get(self, kind: str, locale: str, firm: str = "") -> bytes | None:
        """Return cached bytes, or ``None`` when the optional renderer fails."""
        _validate(kind, locale, firm)
        key = (kind, locale, firm)
        with self._lock:
            if key in self._entries:
                return self._entries[key]
            png = raster.card_png(tool_card_svg(kind, locale, firm))
            if png is not None:
                self._entries[key] = png
            return png

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


__all__ = ["CARD_SIZE", "TOOL_KINDS", "ToolPNGCache", "tool_card_svg", "tool_image_path"]
