"""The longest losing run next to the one chance gives at the same loss rate."""

from __future__ import annotations

import itertools
import math
from datetime import UTC, datetime, timedelta

import numpy as np

from quant_trade.audit.analytics import trade_statistics
from quant_trade.audit.guard import assert_report_clean
from quant_trade.audit.i18n import spanish
from quant_trade.audit.report import LABELS, render_html
from quant_trade.audit.sample import sample_result
from quant_trade.audit.streaks import (
    EXACT_MAX_TRADES,
    KEYS,
    longest_run_tail,
    loss_streak_review,
    shuffle_tail,
)
from quant_trade.core.models import Trade


def _brute_tail(n: int, q: float, k: int) -> float:
    total = 0.0
    for outcome in itertools.product((True, False), repeat=n):
        run = best = 0
        for lost in outcome:
            run = run + 1 if lost else 0
            best = max(best, run)
        if best >= k:
            losses = sum(outcome)
            total += q**losses * (1 - q) ** (n - losses)
    return total


def test_the_recurrence_matches_every_ordering() -> None:
    for n, q in ((6, 0.5), (9, 0.3), (10, 0.7)):
        tail = longest_run_tail(n, q, n)
        assert tail[0] == 1.0
        for k in range(1, n + 1):
            assert math.isclose(tail[k], _brute_tail(n, q, k), abs_tol=1e-12)


def test_an_ordinary_streak_is_what_chance_gives() -> None:
    rng = np.random.default_rng(5)
    pnl = np.where(rng.random(400) < 0.45, -1.0, 1.0)
    streak = loss_streak_review(pnl)
    assert streak["losing_run_chance"]["evidence"] == "MEASURED"
    assert streak["losing_run_chance"]["value"] < streak["losing_run_rare"]["value"]
    assert streak["losing_run_odds"]["value"] > 0.05


def test_losses_bunched_together_are_rare_by_chance() -> None:
    # The same 60 losses of 200 trades, all in one block.
    pnl = [1.0] * 70 + [-1.0] * 60 + [1.0] * 70
    streak = loss_streak_review(pnl)
    assert streak["losing_run_odds"]["value"] < 1e-9
    assert streak["losing_run_rare"]["value"] < 60


def test_the_streak_needs_enough_trades_and_some_losses() -> None:
    for pnl in ([-1.0, 1.0] * 5, [1.0] * 40, [-1.0] * 40):
        streak = loss_streak_review(pnl)
        assert set(streak) == set(KEYS)
        assert all(item["evidence"] == "NOT_MEASURED" for item in streak.values())
        assert all(spanish(item["note"]) for item in streak.values())


def test_the_report_puts_the_streak_next_to_chance() -> None:
    result = sample_result("es", bootstrap_samples=60)
    stats = result.model_dump(mode="json")["trade_stats"]
    for key in KEYS:
        assert stats[key]["evidence"] == "MEASURED"
        assert spanish(stats[key]["note"])
    es = render_html(result, watermark=False)
    assert "Con el mismo porcentaje de perdedoras y en orden al azar" in es
    assert f"Este historial tuvo {stats['max_consecutive_losses']['value']}." in es
    en = render_html(sample_result("en", bootstrap_samples=60), watermark=False)
    assert "the longest losing run is typically" in en
    # Bunched losses add the plain warning.
    bunched = dict(stats)
    bunched.update({"max_consecutive_losses": {"value": 60, "evidence": "MEASURED", "note": ""}})
    bunched["losing_run_odds"] = {"value": 1e-12, "evidence": "MEASURED", "note": ""}
    page = render_html(result.model_copy(update={"trade_stats": bunched}), watermark=False)
    assert "Las perdedoras llegaron más juntas de lo que el azar explica" in page
    assert "Las perdedoras llegaron más juntas" not in es
    for locale in ("es", "en"):
        assert_report_clean(LABELS[locale]["streak_line"] + LABELS[locale]["streak_clustered"])
    # A locked preview keeps the figures back.
    assert "orden al azar" not in render_html(result, watermark=True, free_mode=False)


def test_trade_statistics_carries_the_streak() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    trades = [
        Trade(
            entry_time=start + timedelta(days=i),
            exit_time=start + timedelta(days=i, hours=1),
            entry_price=1.0,
            exit_price=1.0,
            quantity=1.0,
            pnl=-1.0 if i % 3 == 0 else 2.0,
            return_pct=0.0,
        )
        for i in range(30)
    ]
    stats = trade_statistics(trades, ["long"] * 30)
    assert stats["max_consecutive_losses"]["value"] == 1
    assert stats["losing_run_odds"]["value"] > 0.99


def _longest(outcome: tuple[bool, ...]) -> int:
    run = best = 0
    for lost in outcome:
        run = run + 1 if lost else 0
        best = max(best, run)
    return best


def test_the_shuffle_odds_match_every_permutation() -> None:
    for n, losses in ((8, 3), (12, 5), (14, 10), (10, 1)):
        orders = [
            tuple(i in chosen for i in range(n))
            for chosen in map(set, itertools.combinations(range(n), losses))
        ]
        for k in range(0, losses + 2):
            share = sum(_longest(order) >= k for order in orders) / len(orders)
            assert math.isclose(shuffle_tail(n, losses, k), share, abs_tol=1e-12)


def test_the_review_uses_the_shuffle_of_the_same_trades() -> None:
    # 30 trades, 6 losses, the four in a row: a shuffle gives about 1.4 %,
    # independent losses at the same rate about 3.4 %.
    pnl = [-1.0] * 4 + [1.0] * 12 + [-1.0] + [1.0] * 6 + [-1.0] + [1.0] * 6
    streak = loss_streak_review(pnl)
    assert math.isclose(streak["losing_run_odds"]["value"], shuffle_tail(30, 6, 4))
    assert 0.010 < streak["losing_run_odds"]["value"] < 0.018
    tail = [shuffle_tail(30, 6, k) for k in range(8)]
    assert streak["losing_run_chance"]["value"] == max(k for k in range(8) if tail[k] >= 0.5)
    assert streak["losing_run_rare"]["value"] == max(k for k in range(8) if tail[k] >= 0.05)


def test_above_the_exact_size_the_recurrence_stands_in() -> None:
    rng = np.random.default_rng(4)
    pnl = np.where(rng.random(EXACT_MAX_TRADES + 1) < 0.4, -1.0, 1.0)
    streak = loss_streak_review(pnl)
    assert streak["losing_run_odds"]["evidence"] == "MEASURED"
    assert 5 <= streak["losing_run_chance"]["value"] <= 20
