"""The recent third of a history against the earlier two thirds. Offline."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from audit_fixtures import business_days, csv_bytes, trades_following

from quant_trade.audit.decay import recent_review
from quant_trade.audit.engine import run_audit
from quant_trade.audit.guard import assert_report_clean
from quant_trade.audit.i18n import untranslated
from quant_trade.audit.report import render
from quant_trade.audit.schema import DeclaredMetadata, build_inputs
from quant_trade.core.models import Trade

T0 = datetime(2020, 1, 1, tzinfo=UTC)


def _trades(results: list[float], *, days_apart: float = 12.0) -> list[Trade]:
    return [
        Trade(
            entry_time=T0 + timedelta(days=days_apart * i),
            exit_time=T0 + timedelta(days=days_apart * i + 1),
            quantity=1.0,
            entry_price=100.0,
            exit_price=100.0,
            pnl=pnl,
            return_pct=0.0,
        )
        for i, pnl in enumerate(results)
    ]


def _noise(n: int, mean: float, seed: int) -> list[float]:
    return [float(v) for v in np.random.default_rng(seed).normal(mean, 10.0, n)]


def test_a_steady_history_holds() -> None:
    review, flags = recent_review(_trades(_noise(120, 3.0, seed=1)))
    assert review["status"] == "MEASURED" and flags == [] and review["clean"] is True
    assert review["early"]["trades"]["value"] + review["recent"]["trades"]["value"] == 120
    assert [row["key"] for row in review["years"]] == [2020, 2021, 2022, 2023]


def test_a_history_that_stops_working_is_flagged() -> None:
    review, flags = recent_review(_trades(_noise(80, 5.0, seed=2) + _noise(40, -3.0, seed=3)))
    assert [(flag.code, flag.severity) for flag in flags] == [("EDGE_FADING", "WARN")]
    assert review["recent"]["mean"]["value"] <= 0 < review["early"]["mean"]["value"]
    assert review["drop_z"]["value"] <= -2
    assert "the last third of the history" in flags[0].detail


def test_a_recent_dip_that_noise_explains_is_not_flagged() -> None:
    # Recent trades average a small loss, but not far enough from the earlier ones.
    results = _noise(80, 1.0, seed=4) + [v + 2.5 for v in _noise(40, 0.0, seed=5)]
    review, flags = recent_review(_trades(results))
    assert review["recent"]["mean"]["value"] <= 0
    assert flags == [] and review["drop_z"]["value"] > -2


def test_fees_count_against_each_trade() -> None:
    results = _noise(120, 3.0, seed=6)
    fees = [0.0] * 80 + [6.0] * 40
    review, flags = recent_review(_trades(results), fees)
    assert review["recent"]["mean"]["value"] < 0
    assert [flag.code for flag in flags] == ["EDGE_FADING"]


@pytest.mark.parametrize(
    ("results", "days_apart", "reason"),
    [
        (_noise(59, 3.0, seed=7), 20.0, "needs at least 60"),
        (_noise(120, 3.0, seed=8), 5.0, "less than two years"),
    ],
)
def test_short_histories_are_not_measured(
    results: list[float], days_apart: float, reason: str
) -> None:
    review, flags = recent_review(_trades(results, days_apart=days_apart))
    assert review["status"] == "NOT_MEASURED" and flags == []
    assert reason in review["reason"]


def test_too_few_recent_trades_are_not_measured() -> None:
    # 100 trades in the first year, then 5 spread over two more years.
    trades = _trades(_noise(100, 3.0, seed=10), days_apart=3.0)
    last = trades[-1].exit_time
    trades += [
        trades[0].model_copy(
            update={
                "entry_time": last + timedelta(days=150 * i),
                "exit_time": last + timedelta(days=150 * i + 1),
            }
        )
        for i in range(1, 6)
    ]
    review, flags = recent_review(trades)
    assert review["status"] == "NOT_MEASURED" and "recent third" in review["reason"]
    assert flags == []


def _curve(parts: list[tuple[int, float]]) -> pd.DataFrame:
    rng = np.random.default_rng(12)
    returns = np.concatenate([rng.normal(mean, 0.004, n) for n, mean in parts])
    equity = 10_000.0 * np.cumprod(1.0 + returns)
    return pd.DataFrame({"timestamp": business_days(len(returns)), "equity": equity})


@pytest.mark.parametrize("locale", ["es", "en"])
def test_engine_flags_and_renders_the_section(locale: str) -> None:
    curve = _curve([(1000, 0.002), (500, -0.0015)])
    inputs = build_inputs(
        csv_bytes(curve),
        DeclaredMetadata(locale=locale),
        trades_bytes=csv_bytes(trades_following(curve, every=10)),
    )
    result = run_audit(inputs, bootstrap_samples=200, risk_samples=300)
    assert result.recent is not None and result.recent["status"] == "MEASURED"
    assert "EDGE_FADING" in {flag["code"] for flag in result.red_flags}
    assert result.verdict.overall != "A"
    html, _ = render(result, watermark=False)
    assert_report_clean(html)
    title = "¿Sigue funcionando en el periodo reciente?" if locale == "es" else "Does it still"
    assert title in html
    assert ("Se apaga" if locale == "es" else "Fades") in html
    assert untranslated(result.model_dump(mode="json")) == []


def test_engine_steady_history_holds() -> None:
    curve = _curve([(1500, 0.001)])
    inputs = build_inputs(
        csv_bytes(curve),
        DeclaredMetadata(locale="es"),
        trades_bytes=csv_bytes(trades_following(curve, every=10)),
    )
    result = run_audit(inputs, bootstrap_samples=200, risk_samples=300)
    assert result.recent is not None and result.recent["clean"] is True
    assert "EDGE_FADING" not in {flag["code"] for flag in result.red_flags}
    html, _ = render(result, watermark=False)
    assert "Se mantiene" in html


def test_small_amounts_keep_their_digits_and_never_show_a_signed_zero() -> None:
    from quant_trade.audit.report import LABELS, _recent_html, _signed_amount

    assert _signed_amount(0.00027) == "+0.00027"
    assert _signed_amount(-0.00014) == "-0.00014"
    assert _signed_amount(-0.0) == "0.00" and _signed_amount(1e-12) != "+0.00"
    assert _signed_amount(-1234.5) == "-1,234.50"
    results = [v / 10_000 for v in _noise(120, 3.0, seed=1)]
    review, _ = recent_review(_trades(results))
    html = _recent_html(review, "es", LABELS["es"])
    assert "-0.00<" not in html and "+0.00<" not in html


def test_the_flag_quotes_small_averages_with_their_digits() -> None:
    results = [v / 1000 for v in _noise(80, 5.0, seed=2) + _noise(40, -3.0, seed=3)]
    _, flags = recent_review(_trades(results))
    assert [flag.code for flag in flags] == ["EDGE_FADING"]
    assert "-0.00 " not in flags[0].detail and "+0.00 " not in flags[0].detail
