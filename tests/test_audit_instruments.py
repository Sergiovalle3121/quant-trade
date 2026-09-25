"""Each instrument's result, and whether one carries the rest. Offline."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from audit_fixtures import business_days, csv_bytes, trades_following

from quant_trade.audit.engine import run_audit
from quant_trade.audit.guard import assert_report_clean, find_claims
from quant_trade.audit.i18n import untranslated
from quant_trade.audit.instruments import OTHER, instrument_review
from quant_trade.audit.report import LABELS, _instruments_html, render
from quant_trade.audit.schema import DeclaredMetadata, build_inputs
from quant_trade.core.models import Trade

T0 = datetime(2024, 1, 1, tzinfo=UTC)


def _trades(pnls: list[float]) -> list[Trade]:
    return [
        Trade(
            entry_time=T0 + timedelta(days=i),
            exit_time=T0 + timedelta(days=i, hours=5),
            quantity=1.0,
            entry_price=100.0,
            exit_price=100.0,
            pnl=pnl,
            return_pct=0.0,
        )
        for i, pnl in enumerate(pnls)
    ]


def _book(parts: dict[str, list[float]]) -> tuple[list[Trade], list[str]]:
    symbols = [name for name, pnls in parts.items() for _ in pnls]
    return _trades([p for pnls in parts.values() for p in pnls]), symbols


def test_a_spread_result_has_no_findings() -> None:
    trades, symbols = _book(
        {"EURUSD": [12.0, -10.0] * 10, "GBPUSD": [12.0, -10.0] * 10, "USDJPY": [12.0, -10.0] * 8}
    )
    review = instrument_review(trades, symbols)
    assert review["status"] == "MEASURED" and review["findings"] == []
    assert [row["key"] for row in review["rows"]] == ["EURUSD", "GBPUSD", "USDJPY"]
    assert review["rows"][0]["net"]["value"] == pytest.approx(20.0)


def test_one_instrument_carrying_the_rest_is_found() -> None:
    trades, symbols = _book(
        {"XAUUSD": [50.0] * 15, "EURUSD": [-5.0, 2.0] * 10, "GBPUSD": [-6.0, 3.0] * 10}
    )
    review = instrument_review(trades, symbols)
    assert review["findings"] == ["one_carries", "most_lose"]
    assert review["best"]["key"] == "XAUUSD" and review["best"]["share"]["value"] > 1
    html = _instruments_html(review, "es", LABELS["es"])
    assert "sin XAUUSD, los demás juntos" in html and "(2 de 3)" in html
    english = _instruments_html(review, "en", LABELS["en"])
    assert "without XAUUSD, the others together" in english
    assert_report_clean(html + english)


def test_small_instruments_share_one_row() -> None:
    trades, symbols = _book(
        {"EURUSD": [12.0, -10.0] * 10, "GBPUSD": [12.0, -10.0] * 10, "A": [5.0] * 3, "B": [-1.0]}
    )
    review = instrument_review(trades, symbols)
    other = review["rows"][-1]
    assert other["key"] == OTHER and other["instruments"]["value"] == 2
    assert other["trades"]["value"] == 4
    html = _instruments_html(review, "es", LABELS["es"])
    assert "Otros (2 con menos de 10 operaciones)" in html and OTHER not in html


def test_fees_count_against_each_trade() -> None:
    trades, symbols = _book({"EURUSD": [3.0] * 20, "GBPUSD": [12.0] * 20})
    review = instrument_review(trades, symbols, [4.0] * 40)
    assert review["rows"][0]["net"]["value"] == pytest.approx(-20.0)
    assert "one_carries" in review["findings"]


@pytest.mark.parametrize(
    ("symbols", "count", "reason"),
    [
        (None, 40, "does not name each trade's instrument"),
        (["EURUSD"] * 39 + [""], 40, "does not name each trade's instrument"),
        (["EURUSD"] * 40, 40, "every trade is on one instrument"),
        (["EURUSD", "GBPUSD"] * 10, 20, "needs at least 30"),
    ],
)
def test_single_or_unnamed_instruments_are_not_measured(
    symbols: list[str] | None, count: int, reason: str
) -> None:
    review = instrument_review(_trades([1.0] * count), symbols)
    assert review["status"] == "NOT_MEASURED" and reason in review["reason"]


def test_every_label_passes_the_guard() -> None:
    for labels in LABELS.values():
        for key, text in labels.items():
            if key.startswith("ins_") or key == "instruments":
                assert find_claims(text) == [], text


def _inputs(locale: str):  # type: ignore[no-untyped-def]
    rng = np.random.default_rng(12)
    returns = rng.normal(0.0008, 0.006, 1200)
    curve = pd.DataFrame(
        {"timestamp": business_days(len(returns)), "equity": 10_000.0 * np.cumprod(1 + returns)}
    )
    return build_inputs(
        csv_bytes(curve),
        DeclaredMetadata(locale=locale),
        trades_bytes=csv_bytes(trades_following(curve, every=10)),
    )


@pytest.mark.parametrize("locale", ["es", "en"])
def test_engine_renders_the_section(locale: str) -> None:
    inputs = _inputs(locale)
    count = len(inputs.trades.trades)
    symbols = (["EURUSD", "GBPUSD", "USDJPY"] * count)[:count]
    inputs = dataclasses.replace(inputs, trade_symbols=symbols)
    result = run_audit(inputs, bootstrap_samples=200, risk_samples=300)
    assert result.instruments is not None and result.instruments["status"] == "MEASURED"
    html, _ = render(result, watermark=False)
    assert_report_clean(html)
    assert LABELS[locale]["instruments"] in html
    assert untranslated(result.model_dump(mode="json")) == []


def test_a_csv_without_instruments_shows_no_section() -> None:
    result = run_audit(_inputs("es"), bootstrap_samples=200, risk_samples=300)
    assert result.instruments is not None and result.instruments["status"] == "NOT_MEASURED"
    html, _ = render(result, watermark=False)
    assert LABELS["es"]["instruments"] not in html
    assert untranslated(result.model_dump(mode="json")) == []


def test_most_of_the_result_from_one_instrument_is_not_called_spread_out() -> None:
    trades, symbols = _book({"XAUUSD": [20.0] * 20, "EURUSD": [12.0, -10.0] * 10})
    review = instrument_review(trades, symbols)
    assert review["findings"] == ["mostly_one"] and review["best"]["share"]["value"] > 0.9
    html = _instruments_html(review, "es", LABELS["es"])
    assert "Repartido" not in html and "Casi todo el resultado viene de XAUUSD (95%)" in html
    english = _instruments_html(review, "en", LABELS["en"])
    assert "Almost all of the result comes from XAUUSD" in english
    assert_report_clean(html + english)


def test_a_share_above_the_total_says_the_others_subtract() -> None:
    trades, symbols = _book(
        {"XAUUSD": [50.0] * 15, "EURUSD": [-5.0, 2.0] * 10, "GBPUSD": [12.0, -10.0] * 10}
    )
    review = instrument_review(trades, symbols)
    html = _instruments_html(review, "es", LABELS["es"])
    assert "Más que el resultado neto viene de XAUUSD: los demás juntos restan" in html
