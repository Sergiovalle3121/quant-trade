"""Capital and size for a loss limit, from the closed trades. Offline and seeded."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from audit_fixtures import csv_bytes, positive_drift, trades_following

from quant_trade.audit.engine import run_audit
from quant_trade.audit.guard import assert_report_clean
from quant_trade.audit.i18n import untranslated
from quant_trade.audit.report import render
from quant_trade.audit.schema import DeclaredMetadata, build_inputs
from quant_trade.audit.sizing import LOSS_LIMITS, capital_review, scale_text
from quant_trade.core.models import Trade

START = datetime(2024, 1, 2, 9, 0, tzinfo=UTC)


def _trades(profits: list[float], *, every_days: float = 2.0) -> list[Trade]:
    out = []
    for i, profit in enumerate(profits):
        entry = START + timedelta(days=i * every_days)
        out.append(
            Trade(
                entry_time=entry,
                exit_time=entry + timedelta(hours=4),
                quantity=1.0,
                entry_price=1000.0,
                exit_price=1000.0 + profit,
                pnl=profit,
                return_pct=profit / 1000.0,
            )
        )
    return out


#: 60 trades over four months with a 5-trade losing streak of 100 each.
PROFITS = [60.0, -40.0] * 25 + [-100.0] * 5 + [50.0] * 5


def test_capital_and_size_follow_from_the_reference_fall() -> None:
    review = capital_review(_trades(PROFITS), fees=None, starting_balance=10_000.0, seed=7)
    assert review["status"] == "MEASURED"
    assert review["fall_history"]["value"] == pytest.approx(540.0)
    reference = review["fall_reference"]["value"]
    assert reference == pytest.approx(max(review["fall_p95"]["value"], 540.0))
    assert [row["limit"] for row in review["rows"]] == list(LOSS_LIMITS)
    for row in review["rows"]:
        assert row["capital"]["value"] == pytest.approx(reference / row["limit"])
        assert row["size_share"]["value"] == pytest.approx(row["limit"] * 10_000 / reference)
    assert "shorter than a year" in review["trades_per_year"]["note"]


def test_costs_deepen_the_fall_and_results_are_reproducible() -> None:
    trades = _trades(PROFITS)
    plain = capital_review(trades, fees=None, starting_balance=None, seed=1)
    costly = capital_review(trades, fees=[5.0] * len(trades), starting_balance=None, seed=1)
    assert costly["fall_history"]["value"] > plain["fall_history"]["value"]
    assert plain == capital_review(trades, fees=None, starting_balance=None, seed=1)
    assert plain["rows"][0]["size_share"]["evidence"] == "NOT_MEASURED"


def test_too_little_history_is_not_measured() -> None:
    assert capital_review(_trades([10.0] * 10), fees=None, starting_balance=1.0)["status"] == (
        "NOT_MEASURED"
    )
    crowded = _trades([10.0, -5.0] * 20, every_days=0.1)
    assert capital_review(crowded, fees=None, starting_balance=1.0)["status"] == "NOT_MEASURED"
    winners = _trades([10.0] * 40)
    assert capital_review(winners, fees=None, starting_balance=1.0)["status"] == "NOT_MEASURED"


def test_scale_text() -> None:
    assert scale_text(0.3456) == "0.35x"
    assert scale_text(2.04) == "2.0x"


@pytest.mark.parametrize("locale", ["es", "en"])
def test_section_renders_clean_in_both_languages(locale: str) -> None:
    curve = positive_drift(800)
    inputs = build_inputs(
        csv_bytes(curve),
        DeclaredMetadata(locale=locale, initial_balance=10_000.0),
        trades_bytes=csv_bytes(trades_following(curve, every=10)),
    )
    result = run_audit(inputs, bootstrap_samples=200, risk_samples=300)
    assert result.capital is not None and result.capital["status"] == "MEASURED"
    html, _ = render(result, watermark=False)
    assert_report_clean(html)
    title = "Qué capital necesita y a qué tamaño" if locale == "es" else "How much capital"
    assert title in html
    assert untranslated(result.model_dump(mode="json")) == []


def test_platform_drawdown_with_open_trades_is_a_floor() -> None:
    trades = _trades(PROFITS)
    plain = capital_review(trades, fees=None, starting_balance=10_000.0, seed=3)
    floored = capital_review(
        trades, fees=None, starting_balance=10_000.0, platform_fall=50_000.0, seed=3
    )
    assert plain["fall_platform"]["evidence"] == "NOT_MEASURED"
    assert floored["fall_platform"] == {
        "value": 50_000.0,
        "evidence": "DECLARED",
        "note": "the platform's maximal drawdown in money, open trades included",
    }
    assert floored["fall_reference"]["value"] == pytest.approx(50_000.0)
    assert floored["rows"][1]["capital"]["value"] == pytest.approx(250_000.0)


def test_under_a_year_is_marked_and_under_ninety_days_is_held_back() -> None:
    assert capital_review(_trades(PROFITS), fees=None, starting_balance=1.0)["short_history"]
    short = _trades([10.0, -5.0] * 20, every_days=2.0)
    review = capital_review(short, fees=None, starting_balance=1.0)
    assert review["status"] == "NOT_MEASURED" and "90 days" in review["reason"]


def test_hidden_open_losses_hold_the_figures_back() -> None:
    trades = _trades(PROFITS)
    held = capital_review(trades, fees=None, starting_balance=10_000.0, hidden_open_losses=True)
    assert held["status"] == "NOT_MEASURED"
    assert "closed trades understate the real fall" in held["reason"]
    floored = capital_review(
        trades,
        fees=None,
        starting_balance=10_000.0,
        platform_fall=5_000.0,
        hidden_open_losses=True,
    )
    assert floored["status"] == "MEASURED"
    assert floored["fall_reference"]["value"] == pytest.approx(5_000.0)
    by_curve = capital_review(
        trades, fees=None, starting_balance=10_000.0, curve_fall=4_000.0, hidden_open_losses=True
    )
    assert by_curve["fall_curve"]["evidence"] == "MEASURED"
    assert by_curve["fall_reference"]["value"] == pytest.approx(4_000.0)


def _grid_trades(curve: pd.DataFrame) -> pd.DataFrame:
    """Baskets of five buys, each lower than the last, closed together in profit."""
    stamps = pd.to_datetime(curve["timestamp"], utc=True)
    rows = []
    for start in range(0, len(curve) - 12, 12):
        for level in range(5):
            rows.append(
                {
                    "entry_time": stamps.iloc[start + level],
                    "exit_time": stamps.iloc[start + 10],
                    "quantity": 1.0,
                    "entry_price": 100.0 - level,
                    "exit_price": 101.0,
                    "side": "long",
                }
            )
    return pd.DataFrame(rows)


@pytest.mark.parametrize("scale", [1.0, 1 / 10_000])
def test_grid_is_sized_on_a_money_curve_and_held_back_on_an_index(scale: float) -> None:
    curve = positive_drift(400)
    curve["equity"] = curve["equity"] * scale
    inputs = build_inputs(
        csv_bytes(curve),
        DeclaredMetadata(initial_balance=10_000.0),
        trades_bytes=csv_bytes(_grid_trades(curve)),
    )
    result = run_audit(inputs, bootstrap_samples=200, risk_samples=300)
    assert "GRID_AVERAGING" in {flag["code"] for flag in result.red_flags}
    capital = result.capital
    assert capital is not None
    if scale == 1.0:
        assert capital["status"] == "MEASURED"
        assert capital["fall_curve"]["evidence"] == "MEASURED"
        assert capital["fall_reference"]["value"] >= capital["fall_curve"]["value"]
    else:
        assert capital["status"] == "NOT_MEASURED"
        assert "open losses" in capital["reason"]
    assert untranslated(result.model_dump(mode="json")) == []
