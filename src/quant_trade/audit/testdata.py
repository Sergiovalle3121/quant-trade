"""What data the backtest ran on: tick model, data quality and test window.

The header of a MetaTrader tester report says how the test was modelled
("Every tick", "Control points", "Open prices only"), how complete the price
history was (MT4 "Modelling quality", MT5 "History Quality") and which window
was requested. Buyers of robots are warned that this header is the part of a
report most often edited (the "99 % modelling quality" screenshot) and the
part sellers skip: a strategy tested on coarse or patchy data can show a
result the price path never allowed.

Every figure here is the platform's own statement (DECLARED) except the
count of trades outside the window the header names, which the audit
measures from the rows. A header that does not fit its own model or its own
trades is a question for the seller, not proof of an edit. None of it says
how the strategy will do.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from quant_trade.audit.importers import (
    MT4_TESTER_HTML,
    MT5_TESTER_HTML,
    MT5_TESTER_XLSX,
    _lead_num,
)
from quant_trade.audit.redflags import RedFlag
from quant_trade.audit.schema import ParsedTrades, declared, measured, not_measured

#: Formats whose header states how the test was modelled.
TESTER_FORMATS: frozenset[str] = frozenset({MT4_TESTER_HTML, MT5_TESTER_HTML, MT5_TESTER_XLSX})

#: Data quality below this share makes the data dimension weak ...
QUALITY_WARN = 0.90
#: ... and below this share fails it.
QUALITY_FAIL = 0.50
#: MT4 prints more than this only for "Every tick" with complete history.
COARSE_MAX_QUALITY = 0.90
#: Days of slack around the tested window (time zones, the last bar's close).
WINDOW_SLACK_DAYS = 1

EVERY_TICK = "every tick"
CONTROL_POINTS = "control points"
OPEN_PRICES = "open prices only"

#: How each MT4 model reads in the terminal languages we have seen reports in.
_MODEL_WORDS: dict[str, tuple[str, ...]] = {
    EVERY_TICK: ("every tick", "все тики", "todos os ticks", "todos los ticks", "каждый тик"),
    CONTROL_POINTS: (
        "control points",
        "контрольные точки",
        "pontos de controle",
        "puntos de control",
    ),
    OPEN_PRICES: (
        "open prices",
        "цены открытия",
        "preços de abertura",
        "precios de apertura",
    ),
}

NOT_TESTER = "the file is not a MetaTrader tester report"
MODEL_NOTE = "the tester's modelling mode, as printed in the report header"
QUALITY_NOTE = "share of the price history the tester had, as printed in the report header"
ERRORS_NOTE = "as printed in the report header"
SPREAD_NOTE = "as printed in the report header; 'Current' is the spread when the test ran"
WINDOW_NOTE = "trades that open or close outside the dates the header says were tested"

_PERCENT = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
_DATE = re.compile(r"(\d{4})\.(\d{2})\.(\d{2})")


def tick_model(raw: str | None) -> str | None:
    """The MT4 modelling mode in plain English, or None when unrecognised."""
    if not raw:
        return None
    lowered = raw.lower()
    for model, words in _MODEL_WORDS.items():
        if any(word in lowered for word in words):
            return model
    return None


def data_quality(raw: str | None) -> float | None:
    """``"90.00%"`` or ``"100% real ticks"`` as a share; None for ``"n/a"``."""
    if not raw or "%" not in raw:
        return None
    found = _PERCENT.search(raw)
    value = float(found.group(1).replace(",", ".")) if found else None
    return value / 100.0 if value is not None and 0 <= value <= 100 else None


def stated_window(raw: str | None) -> tuple[date, date] | None:
    """The requested dates: the last two dates in the header's period."""
    found = _DATE.findall(raw or "")
    if len(found) < 2:
        return None
    try:
        start, end = (date(int(y), int(m), int(d)) for y, m, d in found[-2:])
    except ValueError:
        return None
    return (start, end) if start <= end else None


def _outside(trades: ParsedTrades, window: tuple[date, date]) -> int:
    start = window[0] - timedelta(days=WINDOW_SLACK_DAYS)
    end = window[1] + timedelta(days=WINDOW_SLACK_DAYS)
    return sum(
        1
        for trade in trades.trades
        if not (start <= trade.entry_time.date() <= end and start <= trade.exit_time.date() <= end)
    )


def review_test_data(
    *,
    source_format: str,
    metadata: dict[str, str],
    trades: ParsedTrades | None,
) -> tuple[dict[str, Any], list[RedFlag]]:
    """Tick model, data quality and test window of a MetaTrader tester report."""
    if source_format not in TESTER_FORMATS:
        return {"status": "NOT_MEASURED", "reason": NOT_TESTER}, []
    mt4 = source_format == MT4_TESTER_HTML
    raw_quality = metadata.get("modelling_quality" if mt4 else "history_quality")
    quality = data_quality(raw_quality)
    model = tick_model(metadata.get("model")) if mt4 else None
    real_ticks = not mt4 and "real ticks" in (raw_quality or "").lower()
    errors = _lead_num(metadata.get("mismatched_chart_errors")) if mt4 else None
    window = stated_window(metadata.get("period"))
    outside = _outside(trades, window) if window is not None and trades and trades.trades else None

    review: dict[str, Any] = {
        "status": "MEASURED",
        "platform": "MT4" if mt4 else "MT5",
        "tick_model": (
            declared(model, MODEL_NOTE)
            if model
            else declared("real ticks", MODEL_NOTE)
            if real_ticks
            else not_measured("the report does not state a modelling mode we recognise")
        ),
        "data_quality": (
            declared(quality, QUALITY_NOTE)
            if quality is not None
            else not_measured("the report prints no data quality (n/a)")
        ),
        "tested_from": (
            declared(window[0].isoformat(), "as printed in the report header")
            if window
            else not_measured("the report prints no test window")
        ),
        "tested_to": (
            declared(window[1].isoformat(), "as printed in the report header")
            if window
            else not_measured("the report prints no test window")
        ),
        "trades_outside_window": (
            measured(outside, WINDOW_NOTE)
            if outside is not None
            else not_measured("no test window or no trades to compare")
        ),
    }
    if mt4:
        review["mismatched_chart_errors"] = (
            declared(int(errors), ERRORS_NOTE)
            if errors is not None
            else not_measured("the report does not print it")
        )
        spread = (metadata.get("spread") or "").strip()
        review["tester_spread"] = (
            declared(spread, SPREAD_NOTE)
            if spread
            else not_measured("the report does not print it")
        )

    flags: list[RedFlag] = []
    coarse = model in {CONTROL_POINTS, OPEN_PRICES}
    if coarse:
        flags.append(
            RedFlag(
                "COARSE_TICK_MODEL",
                "WARN",
                f"the test ran on {model}: prices between those points were not simulated, "
                "so stops, targets and intrabar exits may have filled where the market never "
                "let them",
            )
        )
    if quality is not None and quality < QUALITY_WARN and not coarse:
        flags.append(
            RedFlag(
                "TEST_DATA_QUALITY_LOW",
                "FAIL" if quality < QUALITY_FAIL else "WARN",
                f"the report states a data quality of {quality:.0%}: part of the price history "
                "was missing or generated",
                quality,
            )
        )
    if coarse and quality is not None and quality > COARSE_MAX_QUALITY:
        flags.append(
            RedFlag(
                "REPORT_HEADER_MISMATCH",
                "WARN",
                f"the header states {quality:.0%} modelling quality with {model}, which MT4 "
                "does not print for that mode; ask for the original report file",
                quality,
            )
        )
    if outside:
        flags.append(
            RedFlag(
                "REPORT_HEADER_MISMATCH",
                "WARN",
                f"{outside} trade(s) fall outside the dates the header says were tested; "
                "ask for the original report file",
                outside,
            )
        )
    review["clean"] = not flags
    return review, flags


__all__ = [
    "QUALITY_FAIL",
    "QUALITY_WARN",
    "TESTER_FORMATS",
    "data_quality",
    "review_test_data",
    "stated_window",
    "tick_model",
]
