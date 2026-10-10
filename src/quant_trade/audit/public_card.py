"""A public post's declared figures in statistical context, never an audit class.

No source is fetched. Win rates are proportions, and a rounded declaration
stays a proportion: we never invent an integer count of successful trades.
"""

from __future__ import annotations

import html
import math
import textwrap
from dataclasses import dataclass
from typing import Literal

from quant_trade.audit.calculator import KURTOSIS, PERIODS_PER_YEAR, SKEW
from quant_trade.audit.engine import sharpe_sampling_variance
from quant_trade.audit.guard import find_claims
from quant_trade.metrics.statistics import expected_max_sharpe

CARD_SIZE = (1200, 675)
MIN_COIN_TRADES = 20

COPY = {
    "es": {
        "title": "Rigor · lectura de cifras públicas",
        "desc": "Cifras declaradas y contexto estadístico; sin archivo ni clase de auditoría.",
        "source": "Fuente declarada",
        "attribution": "Cifras declaradas por quien usó la herramienta",
        "reader_url": "rigorscore.com/lectura",
        "missing": "No declarado",
        "computed": "Calculado a partir de lo declarado",
        "trades": "Operaciones",
        "win_rate": "Aciertos",
        "profit_factor": "Profit factor",
        "sharpe": "Sharpe anual",
        "years": "Años",
        "trials": "Configuraciones",
        "target_r": "Objetivo (R)",
        "stop_r": "Stop (R)",
        "wilson": "Aciertos · intervalo Wilson al 95 %",
        "wilson_note": "Operaciones independientes; porcentaje declarado, quizá redondeado.",
        "wilson_missing": "Faltan operaciones y/o porcentaje de aciertos.",
        "coin": "Mejor resultado esperado de monedas justas",
        "coin_note": "Aproximación normal; tiradas y búsquedas independientes. N es un supuesto.",
        "coin_missing": "Falta el número de operaciones.",
        "coin_short": "La aproximación requiere al menos 20 operaciones.",
        "luck": "Sharpe anual esperado por suerte",
        "luck_note": (
            "Supuesto: 252 datos diarios/año, normales e independientes; pruebas independientes."
        ),
        "null_note": "Sin Sharpe declarado: dispersión bajo la hipótesis nula.",
        "luck_missing": "Faltan años y/o configuraciones.",
        "luck_short": "Se requieren al menos 0,1 años para esta aproximación.",
        "breakeven": "Aciertos de equilibrio antes de costos",
        "breakeven_note": "Supuesto: cada operación termina en el objetivo o en el stop.",
        "breakeven_missing": "Faltan objetivo y/o stop en R.",
        "footer": "No medido: costos, fuera de muestra, calidad de datos.",
        "cta": "Esta tarjeta no es una auditoría; sube el archivo y el informe lo mide.",
    },
    "en": {
        "title": "Rigor · reading public figures",
        "desc": "Declared figures and statistical context; no file or audit class.",
        "source": "Declared source",
        "attribution": "Figures declared by the person who used the tool",
        "reader_url": "rigorscore.com/en/reading",
        "missing": "Not declared",
        "computed": "Computed from declared figures",
        "trades": "Trades",
        "win_rate": "Win rate",
        "profit_factor": "Profit factor",
        "sharpe": "Annual Sharpe",
        "years": "Years",
        "trials": "Configurations",
        "target_r": "Target (R)",
        "stop_r": "Stop (R)",
        "wilson": "Win rate · Wilson 95 % interval",
        "wilson_note": "Independent trades; the declared rate may be rounded.",
        "wilson_missing": "Missing trade count and/or win rate.",
        "coin": "Expected best result from fair coins",
        "coin_note": "Normal approximation; independent flips and searches. N is assumed.",
        "coin_missing": "Missing trade count.",
        "coin_short": "The approximation requires at least 20 trades.",
        "luck": "Expected annual Sharpe from luck",
        "luck_note": (
            "Assumed: 252 normal, independent daily observations/year; independent trials."
        ),
        "null_note": "No declared Sharpe: dispersion under the null hypothesis.",
        "luck_missing": "Missing years and/or configurations.",
        "luck_short": "This approximation requires at least 0.1 years.",
        "breakeven": "Break-even win rate before costs",
        "breakeven_note": "Assumed: every trade ends at the target or the stop.",
        "breakeven_missing": "Missing target and/or stop in R.",
        "footer": "Not measured: costs, out-of-sample, data quality.",
        "cta": "This card is not an audit; upload the file and the report measures it.",
    },
    "pt": {
        "title": "Rigor · leitura de números públicos",
        "desc": "Números declarados e contexto estatístico; sem arquivo nem classe de auditoria.",
        "source": "Fonte declarada",
        "attribution": "Números declarados por quem usou a ferramenta",
        "reader_url": "rigorscore.com/pt/leitura",
        "missing": "Não declarado",
        "computed": "Calculado a partir do declarado",
        "trades": "Operações",
        "win_rate": "Acertos",
        "profit_factor": "Profit factor",
        "sharpe": "Sharpe anual",
        "years": "Anos",
        "trials": "Configurações",
        "target_r": "Alvo (R)",
        "stop_r": "Stop (R)",
        "wilson": "Acertos · intervalo Wilson de 95 %",
        "wilson_note": "Operações independentes; a taxa declarada pode estar arredondada.",
        "wilson_missing": "Faltam operações e/ou taxa de acertos.",
        "coin": "Melhor resultado esperado de moedas justas",
        "coin_note": "Aproximação normal; lançamentos e buscas independentes. N é suposto.",
        "coin_missing": "Falta o número de operações.",
        "coin_short": "A aproximação requer pelo menos 20 operações.",
        "luck": "Sharpe anual esperado por sorte",
        "luck_note": (
            "Suposto: 252 dados diários/ano, normais e independentes; testes independentes."
        ),
        "null_note": "Sem Sharpe declarado: dispersão sob a hipótese nula.",
        "luck_missing": "Faltam anos e/ou configurações.",
        "luck_short": "Esta aproximação requer pelo menos 0,1 anos.",
        "breakeven": "Taxa de acertos de equilíbrio antes dos custos",
        "breakeven_note": "Suposto: cada operação termina no alvo ou no stop.",
        "breakeven_missing": "Faltam alvo e/ou stop em R.",
        "footer": "Não medido: custos, fora da amostra, qualidade dos dados.",
        "cta": "Este cartão não é uma auditoria; envie o arquivo e o relatório faz a medição.",
    },
}


@dataclass(frozen=True)
class PublicClaim:
    source_handle: str = ""
    source_url: str = ""
    trades: int | None = None
    win_rate: float | None = None
    profit_factor: float | None = None
    sharpe: float | None = None
    years: float | None = None
    trials: int | None = None
    target_r: float | None = None
    stop_r: float | None = None
    locale: Literal["es", "en", "pt"] = "es"

    def __post_init__(self) -> None:
        if not isinstance(self.locale, str) or self.locale not in COPY:
            raise ValueError("locale must be es, en or pt")
        for name in ("source_handle", "source_url"):
            value = getattr(self, name)
            if not isinstance(value, str) or len(value) > 2048:
                raise ValueError("source must be text of limited length")
            if any(
                ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF or ord(c) in (0xFFFE, 0xFFFF)
                for c in value
            ):
                raise ValueError("source contains unsupported characters")
            if find_claims(value):
                raise ValueError("source contains unsupported wording")
        for name in ("trades", "trials"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or not 1 <= value <= 10_000_000):
                raise ValueError("counts must be positive integers within the supported range")
        for name in ("win_rate", "profit_factor", "sharpe", "years", "target_r", "stop_r"):
            value = getattr(self, name)
            if value is None:
                continue
            if type(value) not in (int, float) or abs(value) > 1e6 or not math.isfinite(value):
                raise ValueError("figures must be finite numbers within the supported range")
            if name == "win_rate" and not 0 <= value <= 1:
                raise ValueError("win_rate must be a proportion between zero and one")
            if name == "profit_factor" and value < 0:
                raise ValueError("profit_factor must be nonnegative")
            if name in ("years", "target_r", "stop_r") and value <= 0:
                raise ValueError("years, target and stop must be positive")


def _wilson(rate: float, trades: int) -> tuple[float, float]:
    """Wilson on the declared proportion, without reconstructing a win count."""
    z = 1.959964
    denominator = 1 + z * z / trades
    centre = (rate + z * z / (2 * trades)) / denominator
    half = z * math.sqrt(rate * (1 - rate) / trades + z * z / (4 * trades**2)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


def breakeven_rate(target_r: float, stop_r: float) -> float:
    """Win rate at which fixed-R wins and losses cancel, before costs."""
    return stop_r / (target_r + stop_r)


_SWAP_SEPARATORS = str.maketrans({",": ".", ".": ","})


def _separators(text: str, locale: str) -> str:
    """``text`` written with a point, in the language's typography: kept in en, with a
    decimal comma (and a point between thousands) in es and pt. Only the format changes."""
    return text if locale == "en" else text.translate(_SWAP_SEPARATORS)


def _num(value: float, locale: str, decimals: int) -> str:
    """An editorial number with the language's separators: 1,000.5 in en, 1.000,5 in es/pt.

    It lives here, not in ``articles`` (which imports this module), so the reader's card,
    the articles and the win-rate calculator share one typography without an import cycle."""
    return _separators(f"{value:,.{decimals}f}", locale)


def _years(value: float, locale: str) -> str:
    """A span in years as the site writes it: two decimals at most (9 weeks over 52 are
    0.17, never 0.173077), with the language's separators. Only the display rounds;
    every calculation keeps the declared value."""
    shown = round(value, 2)
    return _separators(f"{shown if shown else value:g}", locale)


def _pct(value: float, locale: str) -> str:
    """A proportion as a percentage with one decimal: 56.5 % in en, 56,5 % in es/pt."""
    return f"{_num(value * 100, locale, 1)} %"


def _readings(claim: PublicClaim) -> list[tuple[str, str | None, str]]:
    """Title key, computed value (or absent), and the visible assumption/reason."""
    locale = claim.locale
    copy = COPY[locale]
    readings: list[tuple[str, str | None, str]] = []
    if claim.trades is not None and claim.win_rate is not None:
        low, high = _wilson(claim.win_rate, claim.trades)
        interval = f"{_pct(low, locale)} – {_pct(high, locale)}"
        readings.append(("wilson", interval, copy["wilson_note"]))
    else:
        readings.append(("wilson", None, copy["wilson_missing"]))
    if claim.trades is None:
        readings.append(("coin", None, copy["coin_missing"]))
    elif claim.trades < MIN_COIN_TRADES:
        readings.append(("coin", None, copy["coin_short"]))
    else:
        # The same expected maximum of normals as luck.py; a fair coin has p(1-p)=.25.
        rates = [0.5 + expected_max_sharpe(n, 0.25 / claim.trades) for n in (20, 100)]
        coin = f"N=20: {_pct(rates[0], locale)} · N=100: {_pct(rates[1], locale)}"
        readings.append(("coin", coin, copy["coin_note"]))
    if claim.years is None or claim.trials is None:
        readings.append(("luck", None, copy["luck_missing"]))
    elif claim.years < 0.1:
        readings.append(("luck", None, copy["luck_short"]))
    else:
        # Calculator's sampling variance and luck.py's expected maximum, imported.
        # Without a claimed Sharpe, use the null model's spread, never invent an input.
        variance = sharpe_sampling_variance(
            (claim.sharpe or 0.0) / math.sqrt(PERIODS_PER_YEAR),
            SKEW,
            KURTOSIS,
            max(2, round(claim.years * PERIODS_PER_YEAR)),
        )
        luck = expected_max_sharpe(claim.trials, variance) * math.sqrt(PERIODS_PER_YEAR)
        note = copy["luck_note"]
        if claim.sharpe is None:
            note += " " + copy["null_note"]
        readings.append(("luck", f"≈ {_num(luck, locale, 2)}", note))
    if claim.target_r is not None and claim.stop_r is not None:
        rate = breakeven_rate(claim.target_r, claim.stop_r)
        readings.append(("breakeven", _pct(rate, locale), copy["breakeven_note"]))
    else:
        readings.append(("breakeven", None, copy["breakeven_missing"]))
    return readings


def public_card_svg(claim: PublicClaim) -> str:
    """Render a standalone, accessible SVG. Every input/output remains DECLARED."""
    copy = COPY[claim.locale]
    width, height = CARD_SIZE
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc" '
        f'xml:lang="{claim.locale}">',
        f'<title id="title">{html.escape(copy["title"])}</title>',
        f'<desc id="desc">{html.escape(copy["desc"])}</desc>',
        '<rect width="1200" height="675" fill="#f7f6f2"/>',
        '<rect width="8" height="675" fill="#245d85"/>',
    ]

    def text(
        x: int,
        y: int,
        value: str,
        size: int = 16,
        color: str = "#202c36",
        anchor: str = "start",
    ) -> None:
        parts.append(
            f'<text x="{x}" y="{y}" font-family="Arial, sans-serif" font-size="{size}" '
            f'fill="{color}" text-anchor="{anchor}">{html.escape(value)}</text>'
        )

    text(40, 53, copy["title"], 32)
    sources = [source for source in (claim.source_handle, claim.source_url) if source.strip()]
    for index, source in enumerate(sources or [copy["attribution"]]):
        # Keep full escaped attribution in a tooltip, with bounded visible lines.
        parts.append(f"<g><title>{html.escape(source)}</title>")
        visible = source[:99] + "…" if len(source) > 100 else source
        if find_claims(visible):
            raise ValueError("shortened source contains unsupported wording")
        attribution = (
            f"DECLARED · {copy['source']}: {visible}" if sources else f"DECLARED · {visible}"
        )
        # Reserve a full em per character, including wide glyphs in source text.
        # Long URLs shrink instead of being cropped in a raster export.
        text(40, 87 + index * 25, attribution, min(15, 1120 // len(attribution)))
        parts.append("</g>")

    fields = (
        "trades",
        "win_rate",
        "profit_factor",
        "sharpe",
        "years",
        "trials",
        "target_r",
        "stop_r",
    )
    for index, name in enumerate(fields):
        x, y = 40 + (index % 4) * 286, 145 + (index // 4) * 70
        value = getattr(claim, name)
        evidence = "NOT_MEASURED" if value is None else "DECLARED"
        parts.append(f'<g data-field="{name}" data-evidence="{evidence}">')
        text(x, y, f"{copy[name]} · {evidence}", 13, "#4c5b67")
        shown = (
            copy["missing"]
            if value is None
            else (
                _pct(value, claim.locale)
                if name == "win_rate"
                else _years(value, claim.locale)
                if name == "years"
                else _separators(f"{value:g}", claim.locale)
            )
        )
        text(x, y + 29, shown, 24)
        parts.append("</g>")

    for index, (key, value, note) in enumerate(_readings(claim)):
        x, y = 40 + (index % 2) * 570, 278 + (index // 2) * 151
        evidence = "DECLARED" if value is not None else "NOT_MEASURED"
        parts += [
            f'<g data-reading="{key}" data-evidence="{evidence}">',
            f'<rect x="{x}" y="{y}" width="550" height="141" rx="9" '
            'fill="#ffffff" stroke="#d6dde0"/>',
        ]
        label = f"{evidence} · {copy['computed']}" if value is not None else evidence
        text(x + 16, y + 22, label, 12, "#4c5b67")
        text(x + 16, y + 46, copy[key], 17)
        if value is not None:
            text(x + 16, y + 80, value, 27, "#245d85")
        for line_index, line in enumerate(textwrap.wrap(note, width=76)):
            text(
                x + 16, y + (98 if value is not None else 75) + line_index * 16, line, 12, "#4c5b67"
            )
        parts.append("</g>")
    text(40, 613, f"NOT_MEASURED · {copy['footer']}", 17)
    text(1160, 613, copy["reader_url"], 14, "#245d85", anchor="end")
    text(40, 644, copy["cta"], 19)
    parts.append("</svg>")
    return "".join(parts)
