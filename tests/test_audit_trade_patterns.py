"""Martingale, grid, concurrency, payoff and stop red flags on synthetic
trade sequences: one positive and one negative case per code."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np

from quant_trade.audit.redflags import scan_trade_patterns
from quant_trade.audit.schema import ParsedTrades
from quant_trade.core.models import Trade

T0 = datetime(2024, 1, 1, tzinfo=UTC)


def _trade(entry_hours: float, exit_hours: float, qty: float, price: float, pnl: float) -> Trade:
    return Trade(
        entry_time=T0 + timedelta(hours=entry_hours),
        exit_time=T0 + timedelta(hours=exit_hours),
        quantity=qty,
        entry_price=price,
        exit_price=price,
        pnl=pnl,
        return_pct=0.0,
    )


def _parsed(trades: list[Trade], sides: list[str] | None = None) -> ParsedTrades:
    return ParsedTrades(
        trades=trades,
        sides=sides or ["long"] * len(trades),
        client_pnl=[None] * len(trades),
        invalid_rows=0,
    )


def _codes(trades: list[Trade], **kw) -> dict[str, str]:
    return {flag.code: flag.severity for flag in scan_trade_patterns(_parsed(trades), **kw)}


def _sequential(outcomes: list[float], sizes: list[float]) -> list[Trade]:
    return [
        _trade(10 * i, 10 * i + 5, size, 100.0, pnl)
        for i, (pnl, size) in enumerate(zip(outcomes, sizes, strict=True))
    ]


def _clean_sequence(n: int = 60, seed: int = 1) -> list[Trade]:
    rng = np.random.default_rng(seed)
    outcomes = [float(v) for v in rng.normal(1.0, 10.0, n)]
    return _sequential(outcomes, [1.0] * n)


def test_clean_sequence_raises_nothing() -> None:
    assert _codes(_clean_sequence()) == {}
    assert _codes([]) == {}


def test_martingale_doubling_after_losses_fails() -> None:
    rng = np.random.default_rng(3)
    outcomes: list[float] = []
    sizes: list[float] = []
    size = 1.0
    for _ in range(60):
        pnl = float(rng.choice([-1.0, 1.0])) * size
        outcomes.append(pnl)
        sizes.append(size)
        size = size * 2 if pnl < 0 else 1.0
        size = min(size, 64.0)
    codes = _codes(_sequential(outcomes, sizes))
    assert codes["MARTINGALE_SIZING"] == "FAIL"


def test_mild_size_increase_after_losses_warns() -> None:
    outcomes = [(-1.0 if i % 2 else 1.0) for i in range(40)]
    sizes = [1.0] + [1.3 if outcomes[i - 1] < 0 else 1.0 for i in range(1, 40)]
    codes = _codes(_sequential(outcomes, sizes))
    assert codes["MARTINGALE_SIZING"] == "WARN"


def test_grid_averaging_down_fails_and_counts_concurrency() -> None:
    trades: list[Trade] = []
    for cycle in range(6):
        base = 200.0 * cycle
        # Five buys, each lower than the last, all closed together.
        for level in range(5):
            trades.append(_trade(base + level, base + 50, 1.0, 100.0 - level, 1.0))
    codes = _codes(trades)
    assert codes["GRID_AVERAGING"] == "FAIL"
    assert codes["MANY_CONCURRENT_POSITIONS"] == "WARN"
    assert _codes(trades, balance_only=True)["HIDDEN_FLOATING_DRAWDOWN"] == "WARN"


def test_adding_at_better_prices_or_other_symbols_is_not_a_grid() -> None:
    pyramid = [_trade(level, 50, 1.0, 100.0 + level, 1.0) for level in range(3)] * 1
    assert "GRID_AVERAGING" not in _codes(pyramid)
    spread = [_trade(level, 50, 1.0, 100.0 - level, 1.0) for level in range(6)]
    by_symbol = scan_trade_patterns(_parsed(spread), symbols=[f"S{i}" for i in range(6)])
    assert {flag.code for flag in by_symbol} == set()


def test_short_grid_adds_at_higher_prices() -> None:
    trades = [_trade(level, 50, 1.0, 100.0 + level, 1.0) for level in range(12)]
    flags = scan_trade_patterns(_parsed(trades, ["short"] * 12))
    assert {flag.code: flag.severity for flag in flags}["GRID_AVERAGING"] == "FAIL"


def test_high_win_rate_with_large_losses_warns() -> None:
    outcomes = [1.0] * 27 + [-6.0] * 3
    codes = _codes(_sequential(outcomes, [1.0] * 30))
    assert codes["NEGATIVE_PAYOFF_HIGH_WINRATE"] == "WARN"
    balanced = [1.0] * 27 + [-2.0] * 3
    assert "NEGATIVE_PAYOFF_HIGH_WINRATE" not in _codes(_sequential(balanced, [1.0] * 30))


def test_no_stop_evidence_from_losses_and_excursions() -> None:
    outcomes = [2.0] * 20 + [-1.0] * 11 + [-40.0]
    codes = _codes(_sequential(outcomes, [1.0] * 32))
    assert codes["NO_STOP_EVIDENCE"] == "WARN"

    capped = [2.0] * 20 + [-1.0] * 12
    trades = _sequential(capped, [1.0] * 32)
    assert "NO_STOP_EVIDENCE" not in _codes(trades)
    excursions: list[float | None] = [None] * 31 + [9.0]
    flags = scan_trade_patterns(_parsed(trades), adverse_excursion=excursions)
    flag = next(f for f in flags if f.code == "NO_STOP_EVIDENCE")
    assert "adverse excursion" in flag.detail


def _with_best(best: float, n: int = 40, each: float = 1.0) -> list[Trade]:
    rest = [_trade(10 * i, 10 * i + 5, 1.0, 100.0, each) for i in range(n - 1)]
    return [*rest, _trade(10 * n, 10 * n + 5, 1.0, 100.0, best)]


def test_one_trade_carrying_the_result_fails() -> None:
    assert _codes(_with_best(1e9))["PROFIT_CONCENTRATION"] == "FAIL"
    assert _codes(_with_best(60.0))["PROFIT_CONCENTRATION"] == "WARN"
    assert "PROFIT_CONCENTRATION" not in _codes(_with_best(5.0))
    assert "PROFIT_CONCENTRATION" not in _codes(_with_best(1e9, n=9))
    # Under 20 trades it only warns; from 20 on a lone trade fails.
    assert _codes(_with_best(1e9, n=12))["PROFIT_CONCENTRATION"] == "WARN"
    assert _codes(_with_best(1000.0, n=29, each=0.1))["PROFIT_CONCENTRATION"] == "FAIL"


def _sequence(pnl: list[float]) -> list[Trade]:
    return [_trade(10 * i, 10 * i + 5, 1.0, 100.0, value) for i, value in enumerate(pnl)]


def test_a_split_big_trade_still_fails() -> None:
    assert _codes(_sequence([500.0, 500.0] + [1.0] * 58))["PROFIT_CONCENTRATION"] == "FAIL"


def test_a_winner_cancelled_by_a_loser_is_not_concentration() -> None:
    assert "PROFIT_CONCENTRATION" not in _codes(_sequence([1000.0, -1000.0] + [1.0] * 58))


def test_shares_round_down_so_a_border_case_never_prints_the_threshold() -> None:
    flags = scan_trade_patterns(_parsed(_sequence([998.0] + [1.0] * 1002)))
    assert flags == [] or "50.0%" not in flags[0].detail
    detail = next(
        f.detail
        for f in scan_trade_patterns(_parsed(_sequence([60.0] + [1.0] * 39)))
        if f.code == "PROFIT_CONCENTRATION"
    )
    assert "60.6%" in detail and "39.3%" in detail


def test_five_trades_carrying_all_of_it_warn() -> None:
    losers = [_trade(10 * i, 10 * i + 5, 1.0, 100.0, -1.0) for i in range(40)]
    winners = [_trade(500 + i, 505 + i, 1.0, 100.0, 20.0) for i in range(5)]
    flags = scan_trade_patterns(_parsed(losers + winners))
    flag = next(flag for flag in flags if flag.code == "PROFIT_CONCENTRATION")
    assert flag.severity == "WARN" and "best 5 trades" in flag.detail


def test_one_trade_result_is_class_d_and_renders_clean() -> None:
    import pandas as pd
    from audit_fixtures import csv_bytes, positive_drift, trades_following

    from quant_trade.audit.engine import run_audit
    from quant_trade.audit.guard import assert_report_clean
    from quant_trade.audit.i18n import untranslated
    from quant_trade.audit.report import render
    from quant_trade.audit.schema import DeclaredMetadata, build_inputs

    curve = positive_drift(800)
    trades = trades_following(curve, every=10)
    big = trades.iloc[[-1]].copy()
    big["exit_price"] = 100.0 + 1e6 / 100.0
    trades = pd.concat([trades.iloc[:-1], big], ignore_index=True)
    for locale in ("es", "en"):
        inputs = build_inputs(
            csv_bytes(curve), DeclaredMetadata(locale=locale), trades_bytes=csv_bytes(trades)
        )
        result = run_audit(inputs, bootstrap_samples=200, risk_samples=300)
        flag = next(f for f in result.red_flags if f["code"] == "PROFIT_CONCENTRATION")
        assert flag["severity"] == "FAIL" and result.verdict.overall == "D"
        html, _ = render(result, watermark=False)
        assert_report_clean(html)
        assert untranslated(result.model_dump(mode="json")) == []
