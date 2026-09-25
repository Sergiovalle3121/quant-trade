"""Capital and size for a loss limit, from the closed trades. Offline and seeded."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

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
