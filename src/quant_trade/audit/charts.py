"""Inline SVG charts for the audit report, without JavaScript.

Four figures turn the report's numbers into something a trader reads at a
glance: the equity curve, the drawdown (underwater) curve, the fan of
resampled one-year scenarios, and a heatmap table of monthly returns.

Design rules, all tested:

- Plain inputs only (timestamps, floats, a mapping of percentile paths), so
  this module depends on nothing but the standard library and pandas for
  timestamp parsing. The engine and analytics compute; this module draws.
- No JavaScript and no event attributes. Every SVG has ``role="img"``, a
  ``<title>`` and a ``<desc>``; every piece of text goes through
  ``html.escape``. Native ``<title>`` tooltips on heatmap cells stand in for
  hover.
- Every figure carries its evidence tag in the caption. A chart with fewer
  than two finite points renders as NOT_MEASURED with a short reason
  instead of an empty plot.
- The fan says, in its own caption, that it is resampled from the uploaded
  history and is not a forecast. No text here states or implies that money
  was or will be made; every output passes ``audit/guard.py``.

Colors come from a validated light palette: blue for the series and the
sequential fan bands, a blue/red diverging pair with a gray midpoint for
monthly returns (so the heatmap does not rely on red versus green), and the
value printed in each cell so color is never the only encoding. The report
itself is light-only, so no dark variant is drawn.
"""

from __future__ import annotations

import html
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, TypeAlias

import pandas as pd

WIDTH = 720
HEIGHT = 260
MARGIN_LEFT = 64
MARGIN_RIGHT = 16
MARGIN_TOP = 14
MARGIN_BOTTOM = 30
DEFAULT_MAX_POINTS = 400
FAN_PERCENTILES = ("p5", "p25", "p50", "p75", "p95")

INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
GRID = "#e4e3df"
SERIES = "#2a78d6"
SERIES_DARK = "#1c5cab"
BAND_OUTER = "#cde2fb"
BAND_INNER = "#86b6ef"
DRAWDOWN_FILL = "#f6d3d3"
DRAWDOWN_LINE = "#b42e2e"
NEUTRAL = "#f0efec"
POSITIVE = "#1c5cab"
NEGATIVE = "#b42e2e"

EVIDENCE_TAGS = ("MEASURED", "DECLARED", "NOT_MEASURED")

TEXT: dict[str, dict[str, str]] = {
    "es": {
        "equity_title": "Curva de equity",
        "equity_desc": "Equity del archivo aportado a lo largo del tiempo.",
        "drawdown_title": "Drawdown (caída desde el máximo previo)",
        "drawdown_desc": "Distancia porcentual de la equity respecto a su máximo anterior.",
        "fan_title": "Abanico de escenarios remuestreados",
        "fan_desc": ("Percentiles de trayectorias de equity remuestreadas del historial aportado."),
        "fan_note": (
            "Remuestreado del historial aportado; no es un pronóstico ni describe "
            "resultados futuros."
        ),
        "monthly_title": "Retornos mensuales",
        "monthly_desc": "Retorno de cada mes natural calculado desde la equity aportada.",
        "year": "Año",
        "total": "Total",
        "median": "mediana",
        "insufficient": "Datos insuficientes para dibujar esta gráfica.",
        "steps": "pasos",
        "points": "puntos",
        "shown": "mostrados",
        "min": "mín.",
        "max": "máx.",
    },
    "en": {
        "equity_title": "Equity curve",
        "equity_desc": "Equity from the supplied file over time.",
        "drawdown_title": "Drawdown (fall from the previous peak)",
        "drawdown_desc": "Percentage distance of equity from its previous peak.",
        "fan_title": "Fan of resampled scenarios",
        "fan_desc": "Percentiles of equity paths resampled from the supplied history.",
        "fan_note": (
            "Resampled from the supplied history; not a forecast and says nothing "
            "about future results."
        ),
        "monthly_title": "Monthly returns",
        "monthly_desc": "Return of each calendar month computed from the supplied equity.",
        "year": "Year",
        "total": "Total",
        "median": "median",
        "insufficient": "Not enough data to draw this chart.",
        "steps": "steps",
        "points": "points",
        "shown": "shown",
        "min": "min",
        "max": "max",
    },
}

MONTHS = {
    "es": ("Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"),
    "en": ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
}

#: Styles the report embeds once; the charts also work without them.
CHART_CSS = """
figure.chart{margin:1em 0;padding:0}
figure.chart svg{width:100%;height:auto;display:block;background:#fcfcfb;border-radius:6px}
figure.chart figcaption{font-size:.85rem;color:#52514e;margin-top:.3em}
table.monthly{border-collapse:collapse;font-size:.8rem;font-variant-numeric:tabular-nums}
table.monthly th,table.monthly td{padding:3px 5px;text-align:right;border:2px solid #fff}
table.monthly td.empty{background:#fafaf8}
.chart-scroll{overflow-x:auto}
.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
@media print{
figure.chart,.chart-scroll{break-inside:avoid;page-break-inside:avoid}
table.monthly td{-webkit-print-color-adjust:exact;print-color-adjust:exact}
figure.chart svg{-webkit-print-color-adjust:exact;print-color-adjust:exact}
}
"""

TimeLike: TypeAlias = str | datetime | date  # pd.Timestamp is a datetime


@dataclass(frozen=True)
class MonthlyReturn:
    year: int
    month: int
    value: float


def _e(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _texts(locale: str) -> dict[str, str]:
    return TEXT.get(locale, TEXT["es"])


def _check_evidence(evidence: str) -> str:
    if evidence not in EVIDENCE_TAGS:
        raise ValueError(f"evidence must be one of {EVIDENCE_TAGS}, got {evidence!r}")
    return evidence


# --------------------------------------------------------------------------
# Data helpers
# --------------------------------------------------------------------------


def downsample(values: Sequence[float], max_points: int = DEFAULT_MAX_POINTS) -> list[int]:
    """Indices of at most ``max_points`` values that keep the shape.

    The first and last points are always kept; the rest of the series is cut
    into equal buckets and each bucket keeps its minimum and its maximum, so
    the global extremes (the deepest drawdown, the highest peak) survive.
    Non-finite values are skipped. Returns sorted, unique indices.
    """
    if max_points < 4:
        raise ValueError("max_points must be at least 4")
    finite = [i for i, v in enumerate(values) if _finite(v)]
    if len(finite) <= max_points:
        return finite
    first, last = finite[0], finite[-1]
    inner = finite[1:-1]
    buckets = (max_points - 2) // 2
    kept = {first, last}
    size = len(inner) / buckets
    for b in range(buckets):
        chunk = inner[int(round(b * size)) : int(round((b + 1) * size))]
        if not chunk:
            continue
        kept.add(min(chunk, key=lambda i: (values[i], i)))
        kept.add(max(chunk, key=lambda i: (values[i], -i)))
    return sorted(kept)


def drawdown_series(equity: Sequence[float]) -> list[float]:
    """Fractional drawdown from the running peak (0 at a peak, negative below).

    Non-finite values give NaN and do not move the peak. A non-positive peak
    makes the fraction undefined, so those points are NaN too.
    """
    out: list[float] = []
    peak = -math.inf
    for value in equity:
        if not _finite(value):
            out.append(math.nan)
            continue
        peak = max(peak, float(value))
        out.append(float(value) / peak - 1.0 if peak > 0 else math.nan)
    return out


def monthly_returns(timestamps: Sequence[TimeLike], equity: Sequence[float]) -> list[MonthlyReturn]:
    """Calendar-month returns from month-end equity.

    The first month is measured from the first observation; every later month
    from the previous month's last observation. Months without observations
    are absent, not zero.
    """
    times, values = _clean_series(timestamps, equity)
    if len(values) < 2:
        return []
    month_end: dict[tuple[int, int], float] = {}
    for t, v in zip(times, values, strict=True):
        month_end[(t.year, t.month)] = v
    out: list[MonthlyReturn] = []
    base = values[0]
    for (year, month), end in sorted(month_end.items()):
        if base > 0:
            out.append(MonthlyReturn(year, month, end / base - 1.0))
        base = end
    return out


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _clean_series(
    timestamps: Sequence[TimeLike], values: Sequence[float]
) -> tuple[list[pd.Timestamp], list[float]]:
    if len(timestamps) != len(values):
        raise ValueError("timestamps and values must have the same length")
    if not len(values):
        return [], []
    parsed = pd.to_datetime(pd.Series(list(timestamps), dtype=object), utc=True, errors="coerce")
    pairs = sorted(
        (t, float(v))
        for t, v in zip(parsed.tolist(), values, strict=True)
        if not pd.isna(t) and _finite(v)
    )
    return [p[0] for p in pairs], [p[1] for p in pairs]


# --------------------------------------------------------------------------
# Scales and ticks
# --------------------------------------------------------------------------


def _nice_ticks(lo: float, hi: float, count: int = 5) -> list[float]:
    if not (math.isfinite(lo) and math.isfinite(hi)):
        return []
    if hi <= lo:
        pad = abs(lo) * 0.05 or 1.0
        lo, hi = lo - pad, hi + pad
    raw = (hi - lo) / max(count - 1, 1)
    magnitude = 10 ** math.floor(math.log10(raw))
    step = next(m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw)
    start = math.floor(lo / step) * step
    ticks = []
    value = start
    while value <= hi + step * 1e-9:
        ticks.append(round(value, 12))
        value += step
    if ticks[-1] < hi:
        ticks.append(round(ticks[-1] + step, 12))
    return ticks


def _fmt_number(value: float) -> str:
    magnitude = abs(value)
    if magnitude >= 1e9:
        return f"{value / 1e9:.1f}B"
    if magnitude >= 1e6:
        return f"{value / 1e6:.1f}M"
    if magnitude >= 1e4:
        return f"{value / 1e3:.0f}k"
    if magnitude >= 100:
        return f"{value:,.0f}"
    if magnitude >= 1:
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return f"{value:.3f}".rstrip("0").rstrip(".") if value else "0"


def _fmt_percent(value: float, digits: int = 0) -> str:
    text = f"{value * 100:.{digits}f}%"
    return text[1:] if text.startswith("-") and not text.strip("-0.%") else text


def _distinct_labels(values: Sequence[float], fmt: Any) -> list[str]:
    """Labels for ``values`` with just enough precision to tell them apart.

    The short form (10k, 0%) is kept when it already separates every value;
    a narrow range (10,020 to 10,080) falls back to full numbers or more
    decimals, so an axis never shows the same label twice.
    """
    labels = [fmt(v) for v in values]
    if (
        fmt is _fmt_number
        and 1e4 <= max(abs(v) for v in values) < 1e6
        and all(v % 1000 == 0 for v in values)
    ):
        # One unit per axis: 8k, 10k, 12k rather than 8,000, 10k, 12k.
        labels = [f"{v / 1e3:g}k" if v else "0" for v in values]
    if len(set(labels)) == len(set(values)):
        return labels
    scale = 100.0 if fmt is _fmt_percent else 1.0
    for digits in (0, 1, 2, 3):
        # The fewest decimals that write every value exactly (ticks are round).
        if all(abs(round(v * scale, digits) - v * scale) < 1e-9 for v in values):
            break
    if fmt is _fmt_percent:
        return [_fmt_percent(v, digits) for v in values]
    return [f"{v:,.{digits}f}" for v in values]


def _fmt_signed_percent(value: float) -> str:
    """A signed share at one decimal; a month that rounds to zero reads 0.0%."""
    shown = f"{value * 100:+,.1f}%"
    return "0.0%" if shown in {"+0.0%", "-0.0%"} else shown


class _Frame:
    """Maps data coordinates to the plot area of a fixed viewBox."""

    def __init__(self, x_lo: float, x_hi: float, y_lo: float, y_hi: float) -> None:
        self.x_lo, self.x_hi = x_lo, x_hi if x_hi > x_lo else x_lo + 1.0
        self.y_lo, self.y_hi = y_lo, y_hi if y_hi > y_lo else y_lo + 1.0
        self.left = MARGIN_LEFT
        self.right = WIDTH - MARGIN_RIGHT
        self.top = MARGIN_TOP
        self.bottom = HEIGHT - MARGIN_BOTTOM

    def x(self, value: float) -> float:
        span = self.x_hi - self.x_lo
        return self.left + (value - self.x_lo) / span * (self.right - self.left)

    def y(self, value: float) -> float:
        span = self.y_hi - self.y_lo
        return self.bottom - (value - self.y_lo) / span * (self.bottom - self.top)


def _path(points: Sequence[tuple[float, float]]) -> str:
    return " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(points))


def _y_axis(frame: _Frame, ticks: Sequence[float], fmt: Any) -> str:
    parts = []
    for tick, label in zip(ticks, _distinct_labels(ticks, fmt), strict=True):
        y = frame.y(tick)
        parts.append(
            f'<line x1="{frame.left}" x2="{frame.right}" y1="{y:.1f}" y2="{y:.1f}" '
            f'stroke="{GRID}" stroke-width="1"/>'
            f'<text x="{frame.left - 6}" y="{y + 4:.1f}" text-anchor="end" '
            f'font-size="11" fill="{INK_SECONDARY}">{_e(label)}</text>'
        )
    return "".join(parts)


def _x_labels(frame: _Frame, labels: Sequence[tuple[float, str]]) -> str:
    y = frame.bottom + 18
    parts = [
        f'<line x1="{frame.left}" x2="{frame.right}" y1="{frame.bottom}" y2="{frame.bottom}" '
        f'stroke="{INK_SECONDARY}" stroke-width="1"/>'
    ]
    for i, (x_value, label) in enumerate(labels):
        anchor = "start" if i == 0 else "end" if i == len(labels) - 1 else "middle"
        parts.append(
            f'<text x="{frame.x(x_value):.1f}" y="{y}" text-anchor="{anchor}" '
            f'font-size="11" fill="{INK_SECONDARY}">{_e(label)}</text>'
        )
    return "".join(parts)


def _time_labels(times: Sequence[pd.Timestamp], count: int = 5) -> list[tuple[float, str]]:
    start, end = times[0], times[-1]
    span_days = (end - start).total_seconds() / 86400
    fmt = "%Y-%m-%d" if span_days < 120 else "%Y-%m"
    picks = [start + (end - start) * (i / (count - 1)) for i in range(count)]
    labels: list[tuple[float, str]] = []
    for t in picks:
        text = t.strftime(fmt)
        if not labels or labels[-1][1] != text:
            labels.append((t.timestamp(), text))
    return labels


def _svg(title: str, desc: str, body: str, uid: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" '
        f'role="img" aria-labelledby="{uid}-t {uid}-d" '
        f'font-family="system-ui,-apple-system,Segoe UI,Roboto,sans-serif">'
        f'<title id="{uid}-t">{_e(title)}</title><desc id="{uid}-d">{_e(desc)}</desc>'
        f"{body}</svg>"
    )


def _figure(inner: str, caption: str, evidence: str, kind: str) -> str:
    return (
        f'<figure class="chart chart-{_e(kind)}">{inner}'
        f'<figcaption><span class="badge {_e(evidence)}">{_e(evidence)}</span> '
        f"{_e(caption)}</figcaption></figure>"
    )


def _insufficient(kind: str, title: str, locale: str) -> str:
    texts = _texts(locale)
    return (
        f'<figure class="chart chart-{_e(kind)} chart-empty">'
        f"<figcaption><strong>{_e(title)}</strong> "
        f'<span class="badge NOT_MEASURED">NOT_MEASURED</span> '
        f"{_e(texts['insufficient'])}</figcaption></figure>"
    )


# --------------------------------------------------------------------------
# Charts
# --------------------------------------------------------------------------


def equity_chart(
    timestamps: Sequence[TimeLike],
    equity: Sequence[float],
    *,
    locale: str = "es",
    evidence: str = "MEASURED",
    note: str | None = None,
    max_points: int = DEFAULT_MAX_POINTS,
) -> str:
    """The equity curve as a ``<figure>`` holding an inline SVG line chart."""
    texts = _texts(locale)
    _check_evidence(evidence)
    times, values = _clean_series(timestamps, equity)
    if len(values) < 2:
        return _insufficient("equity", texts["equity_title"], locale)
    keep = downsample(values, max_points)
    xs = [times[i].timestamp() for i in keep]
    ys = [values[i] for i in keep]
    ticks = _nice_ticks(min(ys), max(ys))
    frame = _Frame(xs[0], xs[-1], ticks[0], ticks[-1])
    line = _path([(frame.x(x), frame.y(y)) for x, y in zip(xs, ys, strict=True)])
    body = (
        _y_axis(frame, ticks, _fmt_number)
        + _x_labels(frame, _time_labels(times))
        + f'<path d="{line}" fill="none" stroke="{SERIES}" stroke-width="2" '
        'stroke-linejoin="round" stroke-linecap="round"/>'
    )
    low, high = _distinct_labels([min(values), max(values)], _fmt_number)
    caption = (
        f"{texts['equity_title']}: {len(values):,} {texts['points']}, "
        f"{texts['min']} {low}, {texts['max']} {high}."
    )
    if note:
        caption += f" {note}"
    svg = _svg(texts["equity_title"], texts["equity_desc"], body, "eq")
    return _figure(svg, caption, evidence, "equity")


def drawdown_chart(
    timestamps: Sequence[TimeLike],
    equity: Sequence[float],
    *,
    locale: str = "es",
    evidence: str = "MEASURED",
    note: str | None = None,
    max_points: int = DEFAULT_MAX_POINTS,
) -> str:
    """The underwater curve, computed from ``equity``, as an area below zero."""
    texts = _texts(locale)
    _check_evidence(evidence)
    times, values = _clean_series(timestamps, equity)
    dd_all = drawdown_series(values)
    pairs = [(t, d) for t, d in zip(times, dd_all, strict=True) if _finite(d)]
    if len(pairs) < 2:
        return _insufficient("drawdown", texts["drawdown_title"], locale)
    times = [p[0] for p in pairs]
    dd = [p[1] for p in pairs]
    keep = downsample(dd, max_points)
    xs = [times[i].timestamp() for i in keep]
    ys = [dd[i] for i in keep]
    worst = min(dd)
    ticks = [t for t in _nice_ticks(min(worst, -0.01), 0.0) if t <= 0]
    frame = _Frame(xs[0], xs[-1], ticks[0], 0.0)
    points = [(frame.x(x), frame.y(y)) for x, y in zip(xs, ys, strict=True)]
    zero = frame.y(0.0)
    area = _path(points) + f" L{points[-1][0]:.1f},{zero:.1f} L{points[0][0]:.1f},{zero:.1f} Z"
    body = (
        _y_axis(frame, ticks, _fmt_percent)
        + _x_labels(frame, _time_labels(times))
        + f'<path d="{area}" fill="{DRAWDOWN_FILL}" stroke="none"/>'
        + f'<path d="{_path(points)}" fill="none" stroke="{DRAWDOWN_LINE}" '
        'stroke-width="1.5" stroke-linejoin="round"/>'
    )
    caption = f"{texts['drawdown_title']}: {texts['max']} {_fmt_percent(worst, 1)}."
    if note:
        caption += f" {note}"
    svg = _svg(texts["drawdown_title"], texts["drawdown_desc"], body, "dd")
    return _figure(svg, caption, evidence, "drawdown")


def fan_chart(
    fan: Mapping[str, Sequence[float]],
    *,
    locale: str = "es",
    evidence: str = "MEASURED",
    horizon_label: str | None = None,
    note: str | None = None,
) -> str:
    """Resampled scenario fan: p5-p95 and p25-p75 bands around the median.

    ``fan`` maps ``p5``, ``p25``, ``p50``, ``p75`` and ``p95`` to equal-length
    equity paths (for example relative equity starting at 1.0). ``p50`` is
    required; a band is drawn only when both of its edges are present. The
    caption always says the paths are resampled and are not a forecast.
    """
    texts = _texts(locale)
    _check_evidence(evidence)
    unknown = set(fan) - set(FAN_PERCENTILES)
    if unknown:
        raise ValueError(f"unknown fan keys: {sorted(unknown)}")
    median = [float(v) for v in fan.get("p50", [])]
    lengths = {len(path) for path in fan.values()}
    if len(lengths) > 1:
        raise ValueError("every fan percentile must have the same length")
    if len(median) < 2 or not all(_finite(v) for path in fan.values() for v in path):
        return _insufficient("fan", texts["fan_title"], locale)
    n = len(median)
    all_values = [float(v) for path in fan.values() for v in path]
    ticks = _nice_ticks(min(all_values), max(all_values))
    frame = _Frame(0.0, float(n - 1), ticks[0], ticks[-1])

    def band(lo_key: str, hi_key: str, color: str) -> str:
        if lo_key not in fan or hi_key not in fan:
            return ""
        upper = [(frame.x(i), frame.y(float(v))) for i, v in enumerate(fan[hi_key])]
        lower = [(frame.x(i), frame.y(float(v))) for i, v in enumerate(fan[lo_key])]
        d = _path(upper + lower[::-1]) + " Z"
        return f'<path d="{d}" fill="{color}" stroke="none"/>'

    start = median[0]
    base_y = frame.y(start)
    median_path = _path([(frame.x(i), frame.y(v)) for i, v in enumerate(median)])
    legend_items = [
        (BAND_OUTER, "p5–p95", ("p5", "p95")),
        (BAND_INNER, "p25–p75", ("p25", "p75")),
        (SERIES_DARK, texts["median"], ("p50",)),
    ]
    legend = ""
    x = frame.left + 8
    for color, label, keys in legend_items:
        if not all(k in fan for k in keys):
            continue
        legend += (
            f'<rect x="{x}" y="{frame.top + 2}" width="12" height="10" rx="2" fill="{color}"/>'
            f'<text x="{x + 16}" y="{frame.top + 11}" font-size="11" fill="{INK}">'
            f"{_e(label)}</text>"
        )
        x += 24 + 7 * len(label)
    x_end = horizon_label or f"{n - 1} {texts['steps']}"
    body = (
        _y_axis(frame, ticks, _fmt_number)
        + _x_labels(frame, [(0.0, "0"), (float(n - 1), x_end)])
        + band("p5", "p95", BAND_OUTER)
        + band("p25", "p75", BAND_INNER)
        + f'<line x1="{frame.left}" x2="{frame.right}" y1="{base_y:.1f}" y2="{base_y:.1f}" '
        f'stroke="{INK_SECONDARY}" stroke-width="1" stroke-dasharray="4 3"/>'
        + f'<path d="{median_path}" fill="none" stroke="{SERIES_DARK}" stroke-width="2" '
        'stroke-linejoin="round"/>' + legend
    )
    caption = f"{texts['fan_title']}. {texts['fan_note']}"
    if note:
        caption += f" {note}"
    svg = _svg(texts["fan_title"], f"{texts['fan_desc']} {texts['fan_note']}", body, "fan")
    return _figure(svg, caption, evidence, "fan")


def _mix(hex_a: str, hex_b: str, t: float) -> str:
    a = [int(hex_a[i : i + 2], 16) for i in (1, 3, 5)]
    b = [int(hex_b[i : i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b, strict=True))


def _cell_style(value: float, scale: float) -> str:
    t = min(abs(value) / scale, 1.0) if scale > 0 else 0.0
    pole = POSITIVE if value >= 0 else NEGATIVE
    background = _mix(NEUTRAL, pole, t)
    color = "#ffffff" if t > 0.65 else INK
    return f"background:{background};color:{color}"


def monthly_heatmap(
    timestamps: Sequence[TimeLike],
    equity: Sequence[float],
    *,
    locale: str = "es",
    evidence: str = "MEASURED",
    note: str | None = None,
) -> str:
    """Monthly returns as an HTML table shaded blue (up) and red (down).

    Each cell prints its value, so the shading is never the only encoding,
    and carries a native tooltip. The last column compounds the year's
    months that have data.
    """
    texts = _texts(locale)
    _check_evidence(evidence)
    months = MONTHS.get(locale, MONTHS["es"])
    rows = monthly_returns(timestamps, equity)
    if not rows:
        return _insufficient("monthly", texts["monthly_title"], locale)
    by_year: dict[int, dict[int, float]] = {}
    for row in rows:
        by_year.setdefault(row.year, {})[row.month] = row.value
    scale = max(abs(r.value) for r in rows)
    head = (
        f"<tr><th>{_e(texts['year'])}</th>"
        + "".join(f"<th>{_e(m)}</th>" for m in months)
        + f"<th>{_e(texts['total'])}</th></tr>"
    )
    body = []
    for year in sorted(by_year):
        cells = []
        for month in range(1, 13):
            value = by_year[year].get(month)
            if value is None:
                cells.append('<td class="empty"></td>')
                continue
            label = f"{year}-{month:02d}: {_fmt_signed_percent(value)}"
            cells.append(
                f'<td style="{_cell_style(value, scale)}" title="{_e(label)}">'
                f"{_e(_fmt_signed_percent(value))}</td>"
            )
        total = math.prod(1.0 + v for v in by_year[year].values()) - 1.0
        total_label = f"{year}: {_fmt_signed_percent(total)}"
        cells.append(
            f'<td style="{_cell_style(total, max(scale, abs(total)))}" '
            f'title="{_e(total_label)}">'
            f"<strong>{_e(_fmt_signed_percent(total))}</strong></td>"
        )
        body.append(f"<tr><th>{year}</th>{''.join(cells)}</tr>")
    table = (
        f'<div class="chart-scroll"><table class="monthly">'
        f"<caption class='sr-only'>{_e(texts['monthly_desc'])}</caption>"
        f"{head}{''.join(body)}</table></div>"
    )
    caption = texts["monthly_title"] + "."
    if note:
        caption += f" {note}"
    return _figure(table, caption, evidence, "monthly")


__all__ = [
    "CHART_CSS",
    "FAN_PERCENTILES",
    "MonthlyReturn",
    "downsample",
    "drawdown_chart",
    "drawdown_series",
    "equity_chart",
    "fan_chart",
    "monthly_heatmap",
    "monthly_returns",
]
