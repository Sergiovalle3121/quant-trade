"""How the trades behave around losses. Offline."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from audit_fixtures import business_days, csv_bytes, trades_following

from quant_trade.audit.behaviour import behaviour_review
from quant_trade.audit.engine import run_audit
from quant_trade.audit.guard import assert_report_clean, find_claims
from quant_trade.audit.i18n import untranslated
from quant_trade.audit.report import LABELS, render
from quant_trade.audit.schema import DeclaredMetadata, build_inputs
from quant_trade.core.models import Trade

T0 = datetime(2024, 1, 1, tzinfo=UTC)


def _trade(entry: datetime, hours: float, pnl: float) -> Trade:
    return Trade(
        entry_time=entry,
        exit_time=entry + timedelta(hours=hours),
        quantity=1.0,
        entry_price=100.0,
        exit_price=100.0,
        pnl=pnl,
        return_pct=0.0,
    )


def _history(pnls: list[float], *, hold: dict[bool, float], gap: dict[bool, float]) -> list[Trade]:
    """Trades one after another: hold and pause in hours by whether the trade won."""
    trades, at = [], T0
    for pnl in pnls:
        won = pnl > 0
        trades.append(_trade(at, hold[won], pnl))
        at = trades[-1].exit_time + timedelta(hours=gap[won])
    return trades


def _mixed(n: int, seed: int) -> list[float]:
    rng = np.random.default_rng(seed)
    return [float(v) if v != 0 else 1.0 for v in rng.choice([-10.0, 12.0], n)]


CALM = {"hold": {True: 5.0, False: 5.0}, "gap": {True: 24.0, False: 24.0}}


def test_a_calm_history_has_no_findings() -> None:
    review = behaviour_review(_history(_mixed(80, seed=1), **CALM))
    assert review["status"] == "MEASURED" and review["findings"] == []
    assert review["hold_ratio"]["value"] == pytest.approx(1.0)
    assert review["quick_after_loss"]["value"] == 0.0


def test_losers_held_longer_is_found() -> None:
    rng = np.random.default_rng(2)
    pnls = _mixed(80, seed=2)
    trades = [
        _trade(T0 + timedelta(days=i), float(rng.uniform(1, 3) * (4 if p < 0 else 1)), p)
        for i, p in enumerate(pnls)
    ]
    review = behaviour_review(trades)
    assert "losers_held_longer" in review["findings"]
    assert review["hold_ratio"]["value"] >= 1.5


def test_a_longer_loser_hold_that_chance_explains_is_not_found() -> None:
    # Medians 1 h against 10 h, but both sides are an even mix of 1 h and 10 h.
    holds = [(12.0, 1.0)] * 8 + [(12.0, 10.0)] * 7 + [(-10.0, 1.0)] * 7 + [(-10.0, 10.0)] * 8
    trades = [_trade(T0 + timedelta(days=i), h, p) for i, (p, h) in enumerate(holds)]
    review = behaviour_review(trades)
    assert review["hold_ratio"]["value"] == pytest.approx(10.0)
    assert "losers_held_longer" not in review["findings"]


def test_quick_reentry_after_losses_is_found() -> None:
    trades = _history(
        _mixed(80, seed=4), hold={True: 5.0, False: 5.0}, gap={True: 24.0, False: 0.1}
    )
    review = behaviour_review(trades)
    assert review["findings"] == ["quick_after_loss"]
    assert review["quick_after_loss"]["value"] == 1.0 and review["quick_after_win"]["value"] == 0


def test_worse_results_after_a_losing_streak_are_found() -> None:
    # Half the trades win, but only one in three after two losses in a row.
    pnls = [12.0, 12.0, 12.0, -10.0, -10.0, -10.0, -10.0, 12.0] * 8
    review = behaviour_review(_history(pnls, **CALM))
    assert "worse_after_streak" in review["findings"]
    assert review["hit_rate_after_streak"]["value"] <= review["hit_rate"]["value"] - 0.15


def test_fees_turn_small_winners_into_losers() -> None:
    pnls = [1.0, -10.0, 12.0, 12.0] * 20
    review = behaviour_review(_history(pnls, **CALM), [2.0] * len(pnls))
    assert review["hit_rate"]["value"] == pytest.approx(0.5)


@pytest.mark.parametrize(
    ("pnls", "reason"),
    [
        ([12.0, -10.0] * 14, "needs at least 30 closed trades"),
        ([12.0] * 35 + [-10.0] * 5, "needs at least 10 winning and 10 losing trades"),
        ([12.0, -10.0] * 15 + [float("nan")], "not a finite number"),
    ],
)
def test_short_or_one_sided_histories_are_not_measured(pnls: list[float], reason: str) -> None:
    review = behaviour_review(_history(pnls, **CALM))
    assert review["status"] == "NOT_MEASURED" and reason in review["reason"]


def test_every_label_passes_the_guard() -> None:
    for labels in LABELS.values():
        for key, text in labels.items():
            if key.startswith("beh") or key == "behaviour":
                assert find_claims(text) == [], text


def _curve() -> pd.DataFrame:
    rng = np.random.default_rng(12)
    returns = rng.normal(0.0008, 0.006, 1200)
    equity = 10_000.0 * np.cumprod(1.0 + returns)
    return pd.DataFrame({"timestamp": business_days(len(returns)), "equity": equity})


@pytest.mark.parametrize("locale", ["es", "en"])
def test_engine_renders_the_section(locale: str) -> None:
    curve = _curve()
    inputs = build_inputs(
        csv_bytes(curve),
        DeclaredMetadata(locale=locale),
        trades_bytes=csv_bytes(trades_following(curve, every=10)),
    )
    result = run_audit(inputs, bootstrap_samples=200, risk_samples=300)
    assert result.behaviour is not None and result.behaviour["status"] == "MEASURED"
    html, _ = render(result, watermark=False)
    assert_report_clean(html)
    assert LABELS[locale]["behaviour"] in html
    assert untranslated(result.model_dump(mode="json")) == []


def test_no_trades_means_no_section() -> None:
    inputs = build_inputs(csv_bytes(_curve()), DeclaredMetadata(locale="es"))
    result = run_audit(inputs, bootstrap_samples=200, risk_samples=300)
    assert result.behaviour == {"status": "NOT_MEASURED", "reason": "no trades uploaded"}
    html, _ = render(result, watermark=False)
    assert LABELS["es"]["behaviour"] not in html
    assert untranslated(result.model_dump(mode="json")) == []


def test_the_findings_render_as_questions() -> None:
    from quant_trade.audit.report import _behaviour_html

    trades = _history(
        _mixed(80, seed=4), hold={True: 2.0, False: 9.0}, gap={True: 24.0, False: 0.1}
    )
    review = behaviour_review(trades)
    html = _behaviour_html(review, "es", LABELS["es"])
    assert "Las perdedoras siguen abiertas bastante más" in html
    assert "Vuelve a entrar deprisa" in html
    assert "Para preguntar" in html and "9.0 h" in html and "2.0 h" in html
    english = _behaviour_html(review, "en", LABELS["en"])
    assert "Losing trades stay open much longer" in english
    assert_report_clean(html + english)


def test_short_losers_keep_their_digits() -> None:
    from quant_trade.audit.report import _ratio_text

    assert _ratio_text(0.036) == "0.036" and _ratio_text(4.52) == "4.5"
    assert _ratio_text(0.1) == "0.1"


def test_equal_reentry_rates_show_no_line() -> None:
    from quant_trade.audit.report import _behaviour_html

    trades = _history(_mixed(80, seed=4), hold={True: 5.0, False: 5.0}, gap={True: 0.1, False: 0.1})
    review = behaviour_review(trades)
    assert review["quick_after_loss"]["value"] == review["quick_after_win"]["value"] == 1.0
    assert "15 minutos" not in _behaviour_html(review, "es", LABELS["es"])


def test_dates_without_a_time_of_day_leave_reentry_unmeasured() -> None:
    from quant_trade.audit.report import _behaviour_html

    # Daily file: after a loss the next trade opens the same day, after a win 5 days later.
    pnls = _mixed(80, seed=4)
    trades, day = [], T0
    for pnl in pnls:
        trades.append(_trade(day, 24.0, pnl))
        day = trades[-1].exit_time + timedelta(days=0 if pnl < 0 else 5)
    review = behaviour_review(trades)
    assert review["quick_after_loss"]["evidence"] == "NOT_MEASURED"
    assert "quick_after_loss" not in review["findings"]
    assert review["hold_ratio"]["evidence"] == "MEASURED"
    html = _behaviour_html(review, "es", LABELS["es"])
    assert "15 minutos" not in html and "Vuelve a entrar" not in html
