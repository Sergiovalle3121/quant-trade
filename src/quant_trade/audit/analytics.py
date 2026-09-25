"""What a trader reads first: trade statistics, resampled risk and a
prop-firm challenge simulator.

Everything here is computed from the uploaded bytes and tagged ``MEASURED``;
what cannot be computed is ``NOT_MEASURED`` with the reason. The resampled
figures (drawdown risk and the challenge simulator) are estimates from a
stationary block bootstrap of the uploaded history. They inherit every
limitation of that history, they assume the future resembles it, and they
are not predictions; each result carries that note in Spanish and English.

Pure functions with explicit seeds: the same input and seed give the same
numbers, so a report can be reproduced byte for byte.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from typing import Any

import numpy as np
import pandas as pd

from quant_trade.audit.prop_presets import ChallengeRules
from quant_trade.audit.schema import MIN_OBSERVATIONS, measured, not_measured
from quant_trade.audit.streaks import loss_streak_review
from quant_trade.core.models import Trade
from quant_trade.research.bootstrap import stationary_bootstrap_indices

#: Van Tharp caps the trade count in SQN at 100 so large samples do not
#: inflate it without bound.
SQN_TRADE_CAP = 100
DAYS_PER_MONTH = 365.25 / 12.0

DRAWDOWN_THRESHOLDS: tuple[float, ...] = (0.10, 0.20, 0.30, 0.50)
FAN_QUANTILES: tuple[int, ...] = (5, 25, 50, 75, 95)
MAX_FAN_POINTS = 120
#: Upper bound on resampled cells (samples x path length) so an intraday
#: upload cannot pin the process; samples are reduced to fit and recorded.
MAX_RESAMPLED_CELLS = 2_000_000
#: Upper bound on the length of one resampled path. A curve sampled faster
#: than about hourly (a year of minute bars is 525 960 periods) is first
#: compounded into consecutive blocks so a path stays this short; without
#: it a curve logged every second asks for hundreds of gigabytes.
MAX_RISK_PATH_PERIODS = 10_000
DEFAULT_BLOCK_SIZE = 5.0
BUSINESS_DAYS_PER_CALENDAR_DAY = 5.0 / 7.0

NO_TRADES = "no trades uploaded"

RESAMPLED_NOTE = "resampled from the uploaded history, not a forecast"
TOO_SHORT_FOR_HORIZON = "the history is too short to resample a year at this frequency"

RISK_ASSUMPTIONS: dict[str, list[str]] = {
    "es": [
        "Estimación remuestreada del historial aportado: no es una predicción.",
        "Supone que el futuro se parece al historial; si el mercado cambia, la estimación no vale.",
        "Una curva de cierres diarios no muestra el drawdown flotante dentro del día.",
    ],
    "en": [
        "Resampled estimate from the supplied history: it is not a prediction.",
        "It assumes the future resembles the history; if the market changes, it no longer holds.",
        "A curve of daily closes does not show floating drawdown within the day.",
    ],
}

CHALLENGE_ASSUMPTIONS: dict[str, list[str]] = {
    "es": [
        "Estimación remuestreada del historial aportado: no es una predicción.",
        "Con datos diarios no se ve el drawdown flotante intradía, así que la estimación es "
        "optimista frente a los límites diarios y totales.",
        "Supone que el futuro se parece al historial y que cada día con retorno distinto de cero "
        "cuenta como día operado.",
        "Las reglas de la firma son las publicadas en la fecha indicada; pueden haber cambiado.",
    ],
    "en": [
        "Resampled estimate from the supplied history: it is not a prediction.",
        "Daily data cannot see intraday floating drawdown, so the estimate is optimistic "
        "against the daily and total limits.",
        "It assumes the future resembles the history and that every day with a non-zero return "
        "counts as a trading day.",
        "The firm's rules are those posted on the date shown; they may have changed.",
    ],
}


# ---------------------------------------------------------------------------
# Trade statistics
# ---------------------------------------------------------------------------

_TRADE_STAT_KEYS: tuple[str, ...] = (
    "trade_count",
    "win_rate",
    "gross_profit",
    "gross_loss",
    "fees_total",
    "net_pnl",
    "profit_factor",
    "expectancy",
    "average_win",
    "average_loss",
    "payoff_ratio",
    "largest_win_share",
    "max_consecutive_wins",
    "max_consecutive_losses",
    "mean_holding_hours",
    "median_holding_hours",
    "sqn",
    "trades_per_month",
)


#: Platforms such as MetaTrader count commission and swap inside each trade,
#: so their profit factor can read a little lower than this one.
PROFIT_FACTOR_NOTE = (
    "gross profit / gross loss, before commission and swap; a platform that counts "
    "them inside each trade can show a slightly lower figure"
)


def _longest_run(flags: Sequence[bool]) -> int:
    longest = run = 0
    for flag in flags:
        run = run + 1 if flag else 0
        longest = max(longest, run)
    return longest


def _side_split(
    pnl: np.ndarray, sides: Sequence[str], side: str, wins_on: np.ndarray | None = None
) -> dict[str, Any]:
    mask = np.array([value == side for value in sides], dtype=bool)
    count = int(mask.sum())
    if count == 0:
        reason = f"no {side} trades"
        return {
            "trade_count": measured(0),
            "win_rate": not_measured(reason),
            "net_pnl": not_measured(reason),
        }
    if wins_on is None:
        return {
            "trade_count": measured(count),
            "win_rate": measured(float((pnl[mask] > 0).mean())),
            "net_pnl": measured(float(pnl[mask].sum()), "before commission and swap"),
        }
    return {
        "trade_count": measured(count),
        "win_rate": measured(float((wins_on[mask] > 0).mean())),
        "net_pnl": measured(
            float(wins_on[mask].sum()), "after the fees the file itemises per trade"
        ),
    }


def trade_statistics(
    trades: Sequence[Trade],
    sides: Sequence[str],
    *,
    fees_total: float = 0.0,
    trade_fees: Sequence[float] | None = None,
) -> dict[str, Any]:
    """Per-trade statistics from closed round trips, ordered by exit time.

    When ``trade_fees`` itemises each trade's cost (aligned with ``trades``,
    positive is a cost), the win rate counts a trade as won only when it
    stays positive after its own fees, the figure every per-trade table of
    the report uses; the gross share is kept as ``win_rate_gross``.

    ``Trade.pnl`` is the gross result of each trade. ``fees_total`` (for
    example commission plus swap from a platform report, as a positive cost)
    cannot be attributed to single trades, so it enters ``net_pnl`` and
    ``expectancy`` only; profit factor, averages and streaks use gross pnl.
    A trade with exactly zero pnl is neither a win nor a loss.
    """
    if len(trades) != len(sides):
        raise ValueError("trades and sides must have the same length")
    if not trades:
        out: dict[str, Any] = {key: not_measured(NO_TRADES) for key in _TRADE_STAT_KEYS}
        out["long"] = {"trade_count": not_measured(NO_TRADES)}
        out["short"] = {"trade_count": not_measured(NO_TRADES)}
        return out

    order = sorted(range(len(trades)), key=lambda i: (trades[i].exit_time, i))
    ordered = [trades[i] for i in order]
    ordered_sides = [sides[i] for i in order]
    pnl = np.array([trade.pnl for trade in ordered], dtype=float)
    n = int(len(pnl))
    itemised = (
        trade_fees is not None
        and len(trade_fees) == len(trades)
        and any(float(fee) != 0 for fee in trade_fees)
    )
    net_each = (
        pnl - np.array([float(trade_fees[i]) for i in order], dtype=float)
        if itemised and trade_fees is not None
        else None
    )
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    gross_profit = float(wins.sum())
    gross_loss = float(losses.sum())
    fees = float(fees_total)
    net = float(pnl.sum()) - fees

    out = {
        "trade_count": measured(n),
        "win_rate": measured(float(len(wins) / n), "share of trades with pnl > 0")
        if net_each is None
        else measured(
            float((net_each > 0).mean()),
            "share of trades with a net profit after the fees the file itemises",
        ),
        "gross_profit": measured(gross_profit),
        "gross_loss": measured(gross_loss),
        "fees_total": measured(fees, "commission and swap as reported, a positive cost")
        if fees
        else not_measured("no commission or swap total supplied"),
        "net_pnl": measured(net, "gross pnl minus reported fees"),
        "expectancy": measured(net / n, "average net result per trade, account currency"),
    }
    if net_each is not None:
        out["win_rate_gross"] = measured(float(len(wins) / n), "share of trades with pnl > 0")
    if len(losses) and gross_loss < 0:
        out["profit_factor"] = measured(gross_profit / abs(gross_loss), PROFIT_FACTOR_NOTE)
    else:
        out["profit_factor"] = not_measured("no losing trades; the ratio is undefined")
    out["average_win"] = (
        measured(float(wins.mean())) if len(wins) else not_measured("no winning trades")
    )
    out["average_loss"] = (
        measured(float(losses.mean())) if len(losses) else not_measured("no losing trades")
    )
    if len(wins) and len(losses):
        out["payoff_ratio"] = measured(
            float(wins.mean() / abs(losses.mean())), "average win / average loss"
        )
    else:
        out["payoff_ratio"] = not_measured("needs at least one win and one loss")
    out["largest_win_share"] = (
        measured(float(wins.max() / gross_profit), "largest single win / gross profit")
        if gross_profit > 0
        else not_measured("no winning trades")
    )
    out["max_consecutive_wins"] = measured(_longest_run([value > 0 for value in pnl]))
    out["max_consecutive_losses"] = measured(_longest_run([value < 0 for value in pnl]))
    out.update(loss_streak_review(pnl))

    hours = np.array(
        [(t.exit_time - t.entry_time).total_seconds() / 3600.0 for t in ordered], dtype=float
    )
    out["mean_holding_hours"] = measured(float(hours.mean()))
    out["median_holding_hours"] = measured(float(np.median(hours)))

    std = float(pnl.std(ddof=1)) if n >= 2 else 0.0
    if n >= 2 and std > 0:
        out["sqn"] = measured(
            math.sqrt(min(n, SQN_TRADE_CAP)) * float(pnl.mean()) / std,
            f"sqrt(min(N, {SQN_TRADE_CAP})) x mean / std of per-trade gross pnl",
        )
    else:
        out["sqn"] = not_measured("needs at least two trades with different results")

    first = min(t.entry_time for t in ordered)
    last = max(t.exit_time for t in ordered)
    span_days = (last - first).total_seconds() / 86400.0
    out["trades_per_month"] = (
        measured(n / (span_days / DAYS_PER_MONTH), "first entry to last exit")
        if span_days >= 1.0
        else not_measured("trades span less than one day")
    )
    out["long"] = _side_split(pnl, ordered_sides, "long", net_each)
    out["short"] = _side_split(pnl, ordered_sides, "short", net_each)
    return out


# ---------------------------------------------------------------------------
# Resampled drawdown risk
# ---------------------------------------------------------------------------


def _clean(returns: pd.Series | np.ndarray | Sequence[float]) -> np.ndarray:
    values = np.asarray(pd.to_numeric(pd.Series(returns), errors="coerce"), dtype=float)
    values = values[np.isfinite(values)]
    # A loss beyond -100 % has no meaning for an account; clip so equity stays >= 0.
    return np.clip(values, -1.0, None)


def _paths(
    values: np.ndarray, *, length: int, samples: int, block_size: float, seed: int
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    block = min(max(float(block_size), 1.0), float(len(values)))
    idx = stationary_bootstrap_indices(
        len(values), length=length, samples=samples, expected_block_size=block, rng=rng
    )
    equity = np.cumprod(1.0 + values[idx], axis=1)
    return np.concatenate([np.ones((samples, 1)), equity], axis=1)


def _max_drawdowns(equity: np.ndarray) -> np.ndarray:
    peaks = np.maximum.accumulate(equity, axis=1)
    return 1.0 - (equity / peaks).min(axis=1)


def _longest_underwater(equity: np.ndarray) -> np.ndarray:
    under = equity < np.maximum.accumulate(equity, axis=1)
    longest = np.zeros(equity.shape[0], dtype=np.int64)
    run = np.zeros(equity.shape[0], dtype=np.int64)
    for column in range(under.shape[1]):
        run = np.where(under[:, column], run + 1, 0)
        longest = np.maximum(longest, run)
    return longest


def _fan(
    equity: np.ndarray, points: int = MAX_FAN_POINTS, *, step: int = 1
) -> dict[str, list[float] | list[int]]:
    length = equity.shape[1]
    positions = np.unique(np.linspace(0, length - 1, min(points, length)).round().astype(int))
    quantiles = np.percentile(equity[:, positions], FAN_QUANTILES, axis=0)
    fan: dict[str, list[float] | list[int]] = {"period": [int(p) * step for p in positions]}
    for q, row in zip(FAN_QUANTILES, quantiles, strict=True):
        fan[f"p{q}"] = [round(float(value), 6) for value in row]
    return fan


def drawdown_risk(
    returns: pd.Series | np.ndarray | Sequence[float],
    *,
    periods_per_year: float,
    samples: int = 2000,
    seed: int = 0,
    block_size: float = DEFAULT_BLOCK_SIZE,
    horizon_years: float = 1.0,
    thresholds: Sequence[float] = DRAWDOWN_THRESHOLDS,
) -> dict[str, Any]:
    """Maximum drawdown over ``horizon_years`` of resampled paths.

    Stationary block bootstrap of the uploaded returns (expected block
    ``block_size`` periods, blocks wrap), ``samples`` paths of one horizon
    each. Reports drawdown quantiles, the share of paths whose drawdown
    reaches each threshold, the longest time under water, and a fan of the
    equity path (p5 to p95, at most ``MAX_FAN_POINTS`` points, equity
    starting at 1.0) for the charts.
    """
    values = _clean(returns)
    thresholds = tuple(float(t) for t in thresholds)
    length = max(2, int(round(periods_per_year * horizon_years)))
    supplied = len(values)
    # Periods compounded into one step of a path (1 unless the curve is
    # finer than MAX_RISK_PATH_PERIODS per horizon); results are reported
    # back in the uploaded periods.
    step = math.ceil(length / MAX_RISK_PATH_PERIODS) if length > MAX_RISK_PATH_PERIODS else 1
    reason = ""
    if supplied < MIN_OBSERVATIONS or float(np.std(values)) <= 0:
        reason = (
            f"needs at least {MIN_OBSERVATIONS} returns that are not all identical; "
            f"{supplied} supplied"
        )
    elif step > 1:
        blocks = supplied // step
        values = np.prod(1.0 + values[: blocks * step].reshape(blocks, step), axis=1) - 1.0
        length = math.ceil(length / step)
        if blocks < MIN_OBSERVATIONS or float(np.std(values)) <= 0:
            reason = TOO_SHORT_FOR_HORIZON
    if reason:
        return {
            "max_drawdown": {key: not_measured(reason) for key in ("p50", "p95", "p99")},
            "probability_drawdown_at_least": {f"{t:.2f}": not_measured(reason) for t in thresholds},
            "longest_underwater_periods": {key: not_measured(reason) for key in ("p50", "p95")},
            "fan": None,
            "method": None,
            "assumptions": RISK_ASSUMPTIONS,
        }
    if samples < 1:
        raise ValueError("samples must be positive")
    used = int(min(samples, max(100, MAX_RESAMPLED_CELLS // length)))
    equity = _paths(values, length=length, samples=used, block_size=block_size, seed=seed)
    drawdowns = _max_drawdowns(equity)
    underwater = _longest_underwater(equity) * step
    note = RESAMPLED_NOTE
    return {
        "max_drawdown": {
            f"p{q}": measured(float(np.percentile(drawdowns, q)), note) for q in (50, 95, 99)
        },
        "probability_drawdown_at_least": {
            f"{t:.2f}": measured(float((drawdowns >= t).mean()), note) for t in thresholds
        },
        "longest_underwater_periods": {
            f"p{q}": measured(float(np.percentile(underwater, q)), note) for q in (50, 95)
        },
        "fan": {"evidence": "MEASURED", "note": note, **_fan(equity, step=step)},
        "method": {
            "bootstrap": "stationary",
            "expected_block_size": min(max(float(block_size), 1.0), float(len(values))),
            "samples": used,
            "samples_requested": int(samples),
            "seed": int(seed),
            "horizon_periods": length * step,
            "periods_per_year": float(periods_per_year),
            "observations": supplied,
            "periods_per_step": step,
        },
        "assumptions": RISK_ASSUMPTIONS,
    }


# ---------------------------------------------------------------------------
# Prop-firm challenge simulator
# ---------------------------------------------------------------------------


def daily_returns_from_equity(frame: pd.DataFrame) -> pd.Series:
    """Close-to-close daily returns from a ``timestamp``/``equity`` frame.

    The last equity value of each UTC calendar day is its close; days
    without a row are skipped, not filled.
    """
    stamps = pd.to_datetime(frame["timestamp"], utc=True)
    equity = pd.Series(frame["equity"].to_numpy(dtype=float), index=stamps)
    closes = equity.groupby(stamps.dt.floor("D").to_numpy()).last()
    return closes.pct_change().replace([np.inf, -np.inf], np.nan).dropna()


def _wilson(successes: int, total: int, z: float = 1.959964) -> tuple[float, float]:
    if total <= 0:
        return 0.0, 1.0
    p = successes / total
    denominator = 1.0 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


def _day_limit(rules: ChallengeRules, max_days: int) -> int:
    if rules.time_limit_days is None:
        return int(max_days)
    business = int(math.floor(rules.time_limit_days * BUSINESS_DAYS_PER_CALENDAR_DAY))
    return max(1, min(int(max_days), business))


BEST_DAY_NOTE = (
    "share of all resampled paths that reach the target with the best day inside the "
    "firm's best-day rule; the rule is checked at the pass, on daily closes"
)


BEST_DAY_BREACH_NOTE = (
    "share of the resampled passes whose best day breaks the firm's best-day rule, "
    "checked at the pass on daily closes"
)


def _best_day_at_pass(
    rules: ChallengeRules,
    passed: np.ndarray,
    best_day: np.ndarray,
    positive: np.ndarray,
    samples: int,
) -> dict[str, Any]:
    """How many passes keep the best day inside the firm's best-day rule."""
    limit = float(rules.best_day_limit or 0.0)
    if rules.best_day_basis == "profit_target":
        within = best_day <= limit * rules.profit_target + 1e-12
    else:
        within = best_day <= limit * positive + 1e-12
    clean = int((passed & within).sum())
    passes = int(passed.sum())
    out: dict[str, Any] = {
        "limit": limit,
        "basis": rules.best_day_basis,
        "pass_within": measured(clean / samples, BEST_DAY_NOTE),
    }
    if passes:
        out["breach_share_of_passes"] = measured((passes - clean) / passes, BEST_DAY_BREACH_NOTE)
    return out


def simulate_challenge(
    daily_returns: pd.Series | np.ndarray | Sequence[float],
    rules: ChallengeRules,
    *,
    samples: int = 5000,
    seed: int = 0,
    block_size: float = DEFAULT_BLOCK_SIZE,
    max_days: int = 250,
) -> dict[str, Any]:
    """Walk resampled daily paths through one challenge phase.

    Each path starts at a balance of 1.0 and is checked at every daily
    close, in this order: the daily loss floor, the total loss floor, then
    the target (reached once the balance is at or above
    ``1 + profit_target`` and at least ``min_trading_days`` days had a
    non-zero return). A path still running after the time limit (calendar
    days converted to business days) or ``max_days`` is unfinished. The four
    probabilities sum to one.
    """
    values = _clean(daily_returns)
    outcome_keys = ("pass", "fail_daily_loss", "fail_total_loss", "unfinished")
    # The last assumption is about a firm's published rules; generic rules have none.
    published = str(rules.to_dict().get("source_url", "")).startswith("https://")
    assumptions = (
        CHALLENGE_ASSUMPTIONS
        if published
        else {locale: lines[:-1] for locale, lines in CHALLENGE_ASSUMPTIONS.items()}
    )
    base: dict[str, Any] = {"rules": rules.to_dict(), "assumptions": assumptions}
    if len(values) < MIN_OBSERVATIONS or float(np.std(values)) <= 0:
        reason = (
            f"needs at least {MIN_OBSERVATIONS} daily returns that are not all identical; "
            f"{len(values)} supplied"
        )
        base["probability"] = {key: not_measured(reason) for key in outcome_keys}
        base["pass_probability_ci95"] = {key: not_measured(reason) for key in ("low", "high")}
        base["days_to_target"] = {key: not_measured(reason) for key in ("p25", "p50", "p75")}
        base["method"] = None
        return base
    if samples < 1 or max_days < 1:
        raise ValueError("samples and max_days must be positive")

    horizon = _day_limit(rules, max_days)
    rng = np.random.default_rng(seed)
    block = min(max(float(block_size), 1.0), float(len(values)))
    idx = stationary_bootstrap_indices(
        len(values), length=horizon, samples=samples, expected_block_size=block, rng=rng
    )
    paths = values[idx]

    target = 1.0 + rules.profit_target
    total_allowance = rules.max_total_loss
    balance = np.ones(samples)
    peak = np.ones(samples)
    traded = np.zeros(samples, dtype=np.int64)
    # Best day and summed positive days, in units of the initial balance.
    best_day = np.zeros(samples)
    positive = np.zeros(samples)
    # 0 running, 1 pass, 2 daily, 3 total
    state = np.zeros(samples, dtype=np.int8)
    day_done = np.full(samples, -1, dtype=np.int64)
    for day in range(horizon):
        running = state == 0
        if not running.any():
            break
        start = balance.copy()
        ret = paths[:, day]
        balance = np.where(running, start * (1.0 + ret), balance)
        traded = traded + (running & (ret != 0.0))
        gain = np.where(running, balance - start, 0.0)
        best_day = np.maximum(best_day, gain)
        positive = positive + np.maximum(gain, 0.0)

        if rules.max_daily_loss is not None:
            if rules.daily_loss_basis == "initial_balance":
                daily_floor = start - rules.max_daily_loss
            else:
                daily_floor = start * (1.0 - rules.max_daily_loss)
            hit = running & (balance < daily_floor - 1e-12)
            state[hit] = 2
            day_done[hit] = day + 1
            running = running & ~hit

        if rules.total_loss_type == "static":
            total_floor = np.full(samples, 1.0 - total_allowance)
        else:
            total_floor = peak - total_allowance
            if rules.total_loss_type == "trailing_eod_lock":
                total_floor = np.minimum(total_floor, 1.0)
        hit = running & (balance < total_floor - 1e-12)
        state[hit] = 3
        day_done[hit] = day + 1
        running = running & ~hit

        passed = running & (balance >= target - 1e-12) & (traded >= rules.min_trading_days)
        state[passed] = 1
        day_done[passed] = day + 1
        peak = np.where(running, np.maximum(peak, balance), peak)

    counts = {
        "pass": int((state == 1).sum()),
        "fail_daily_loss": int((state == 2).sum()),
        "fail_total_loss": int((state == 3).sum()),
        "unfinished": int((state == 0).sum()),
    }
    note = RESAMPLED_NOTE
    base["probability"] = {key: measured(count / samples, note) for key, count in counts.items()}
    low, high = _wilson(counts["pass"], samples)
    ci_note = "Wilson 95 % interval over the resampled paths; it ignores model error"
    base["pass_probability_ci95"] = {
        "low": measured(low, ci_note),
        "high": measured(high, ci_note),
    }
    if rules.best_day_limit is not None:
        base["best_day"] = _best_day_at_pass(rules, state == 1, best_day, positive, samples)
    days = day_done[state == 1]
    if len(days):
        base["days_to_target"] = {
            f"p{q}": measured(float(np.percentile(days, q)), "business days, " + note)
            for q in (25, 50, 75)
        }
    else:
        reason = "no resampled path reached the target within the limits"
        base["days_to_target"] = {key: not_measured(reason) for key in ("p25", "p50", "p75")}
    base["method"] = {
        "bootstrap": "stationary",
        "expected_block_size": block,
        "samples": int(samples),
        "seed": int(seed),
        "horizon_business_days": horizon,
        "observations": int(len(values)),
    }
    return base


# ---------------------------------------------------------------------------
# Questions for the vendor of a trading robot
# ---------------------------------------------------------------------------

#: The shortest live record the vendor is asked for.
LIVE_RECORD_MIN_MONTHS = 6
#: Past this, "at least N months" reads as an unfair ask; the question says what it takes.
LIVE_RECORD_ASK_MONTHS = 24

_QUESTIONS: dict[str, dict[str, str]] = {
    # Asked instead of the backtest questions when the upload is an account history.
    "other_accounts": {
        "es": "¿Es la única cuenta con esta estrategia? Pide también las cuentas que se "
        "cerraron o se reiniciaron: enseñar solo la que salió bien es habitual.",
        "en": "Is this the only account running this strategy? Ask for the accounts that "
        "were closed or restarted too: showing only the one that went well is common.",
    },
    "backtest_match": {
        "es": "Pide el backtest del mismo robot con la misma configuración: subido junto a "
        "esta cuenta, el informe compara los dos operación por operación.",
        "en": "Ask for the backtest of the same robot with the same settings: uploaded "
        "together with this account, the report compares the two trade by trade.",
    },
    "live_record": {
        "es": "¿Hay una cuenta real o demo con al menos {months} meses de historial auditable "
        "con el mismo robot y la misma configuración?",
        "en": "Is there a live or demo account with at least {months} months of auditable "
        "history, with the same robot and settings?",
    },
    "live_record_long": {
        "es": "¿Hay una cuenta real o demo con historial auditable del mismo robot y la misma "
        "configuración? Con un Sharpe como este harían falta unos {months} meses para "
        "distinguirlo del azar: cuanto más largo el historial, mejor.",
        "en": "Is there a live or demo account with auditable history, with the same robot and "
        "settings? With a Sharpe like this one it would take about {months} months to tell it "
        "apart from chance: the longer the history, the better.",
    },
    "modelling": {
        "es": "¿Con qué modo de modelado y calidad de históricos se hizo el backtest "
        "(ticks reales, 1 minuto OHLC, solo precios de apertura)?",
        "en": "Which modelling mode and history quality was the backtest run with "
        "(real ticks, 1-minute OHLC, open prices only)?",
    },
    "best_trade": {
        "es": "¿Qué pasó en la mejor operación (fecha, tamaño, precio) y qué resultado deja el "
        "sistema sin ella?",
        "en": "What happened in the best trade (date, size, price), and what result does the "
        "system leave without it?",
    },
    "recent_period": {
        "es": "¿Qué cambió en el último tramo del historial, en el que las operaciones dejan de "
        "sumar? ¿Se reoptimizó el sistema después?",
        "en": "What changed in the last stretch of the history, where the trades stop adding "
        "up? Was the system reoptimised afterwards?",
    },
    "recent_weaker": {
        "es": "La media por operación del último tramo es menos de la mitad de la anterior: "
        "¿cambió algo en el sistema o en el mercado en ese tiempo?",
        "en": "The average per trade in the last stretch is under half the earlier one: did "
        "anything change in the system or the market over that time?",
    },
    "one_instrument": {
        "es": "Casi todo el resultado viene de un solo instrumento: ¿el sistema se diseñó "
        "para él? ¿Qué resultado dio en los demás?",
        "en": "Almost all of the result comes from one instrument: was the system designed "
        "for it? What did it do on the others?",
    },
    "exit_losses": {
        "es": "Las operaciones perdedoras duran más que las ganadoras: ¿cómo decide el "
        "sistema cerrar una pérdida?",
        "en": "Losing trades last longer than winners: how does the system decide to close "
        "a loss?",
    },
    "after_losses": {
        "es": "¿Qué hace el sistema después de varias pérdidas seguidas: cambia el tamaño, "
        "hace una pausa o vuelve a entrar enseguida?",
        "en": "What does the system do after several losses in a row: change size, pause, or "
        "enter again straight away?",
    },
    "original_file": {
        "es": "¿Puedes enviar el archivo original que exportó MetaTrader, sin editar, con el "
        "encabezado y la lista completa de operaciones?",
        "en": "Can you send the original file MetaTrader exported, unedited, with the header "
        "and the full list of trades?",
    },
    "trials": {
        "es": "¿Cuántas combinaciones de parámetros se probaron antes de elegir esta? "
        "Pide el archivo de optimización.",
        "en": "How many parameter combinations were tried before choosing this one? "
        "Ask for the optimisation file.",
    },
    "out_of_sample": {
        "es": "¿Qué periodo quedó fuera de la optimización y cómo se comportó en él?",
        "en": "Which period was left out of the optimisation, and how did it behave there?",
    },
    "costs": {
        "es": "¿Qué spread, comisión y swap se usaron? ¿Son los de su bróker?",
        "en": "Which spread, commission and swap were used? Are they your broker's?",
    },
    "equity_curve": {
        "es": "Pide la curva de equity (flotante), no solo la de balance: el balance oculta "
        "las pérdidas abiertas.",
        "en": "Ask for the (floating) equity curve, not only the balance: the balance hides "
        "open losses.",
    },
    "trades": {
        "es": "Pide la lista completa de operaciones cerradas con tamaños, precios y fechas.",
        "en": "Ask for the full list of closed trades with sizes, prices and dates.",
    },
    "martingale": {
        "es": "¿El robot aumenta el tamaño después de una pérdida? ¿Cuál es el tamaño máximo "
        "que puede llegar a abrir?",
        "en": "Does the robot increase size after a loss? What is the largest size it can open?",
    },
    "grid": {
        "es": "¿El robot abre posiciones adicionales en contra cuando el precio se aleja? "
        "¿Cuántas como máximo?",
        "en": "Does the robot add positions against the move when price moves away? "
        "How many at most?",
    },
    "stop_loss": {
        "es": "¿Cada operación tiene un stop de pérdida fijo? ¿Cuál fue la mayor pérdida "
        "abierta registrada?",
        "en": "Does every trade have a fixed stop loss? What was the largest open loss recorded?",
    },
    "payoff": {
        "es": "La mayoría de operaciones ganan poco y unas pocas pierden mucho: "
        "¿qué evita una pérdida mayor que las del historial?",
        "en": "Most trades win a little and a few lose a lot: what prevents a loss larger "
        "than those in the history?",
    },
    "deposits": {
        "es": "Pide el historial completo con cada depósito y retiro: ¿cuánto dinero se "
        "depositó en total, cuándo, y cuánto se retiró?",
        "en": "Ask for the full history with every deposit and withdrawal: how much money "
        "was deposited in total, when, and how much was withdrawn?",
    },
    "open_positions": {
        "es": "¿Qué posiciones siguen abiertas, desde cuándo y con qué pérdida flotante?",
        "en": "Which positions are still open, since when, and with what floating loss?",
    },
    "data_quality": {
        "es": "El historial tiene saltos, huecos o valores repetidos: ¿de dónde salen los datos "
        "y cómo se limpiaron?",
        "en": "The history has jumps, gaps or repeated values: where does the data come from "
        "and how was it cleaned?",
    },
}

_FLAG_QUESTIONS: dict[str, str] = {
    "MARTINGALE_SIZING": "martingale",
    "GRID_AVERAGING": "grid",
    "MANY_CONCURRENT_POSITIONS": "grid",
    "HIDDEN_FLOATING_DRAWDOWN": "equity_curve",
    "NO_STOP_EVIDENCE": "stop_loss",
    "PROFIT_CONCENTRATION": "best_trade",
    "NEGATIVE_PAYOFF_HIGH_WINRATE": "payoff",
    "GAIN_INFLATED_BY_FLOWS": "deposits",
    "DEPOSIT_DURING_DRAWDOWN": "deposits",
    "FLOATING_LOSS_AT_END": "open_positions",
    "COARSE_TICK_MODEL": "modelling",
    "TEST_DATA_QUALITY_LOW": "modelling",
    "REPORT_HEADER_MISMATCH": "original_file",
    "ISOLATED_OPTIMUM": "out_of_sample",
    "FORWARD_NOT_HELD": "out_of_sample",
    "EDGE_FADING": "recent_period",
    "MAD_SPIKES": "data_quality",
    "STALE_MARKS": "data_quality",
    "LARGE_GAPS": "data_quality",
    "ZERO_DECLARED_COSTS": "costs",
    "TRIALS_BELOW_VARIANTS": "trials",
}

#: Findings of the report's sections (not red flags) that suggest a question.
_FINDING_QUESTIONS: dict[str, str] = {
    "recent_weaker": "recent_weaker",
    "one_carries": "one_instrument",
    "mostly_one": "one_instrument",
    "losers_held_longer": "exit_losses",
    "quick_after_loss": "after_losses",
    "worse_after_streak": "after_losses",
    "costs_thin": "costs",
}

_QUESTION_ORDER: tuple[str, ...] = tuple(k for k in _QUESTIONS if k != "live_record_long")
#: Questions about how a backtest was made; they do not apply to an account.
_BACKTEST_ONLY: frozenset[str] = frozenset({"modelling", "trials", "out_of_sample", "costs"})


def vendor_questions(
    flag_codes: Iterable[str],
    *,
    has_trades: bool,
    trials_measured: bool,
    has_out_of_sample: bool,
    has_costs: bool,
    balance_only: bool,
    account_history: bool = False,
    min_track_record_months: float | None = None,
    findings: Iterable[str] = (),
) -> list[dict[str, str]]:
    """Questions a buyer can put to the seller of a trading robot.

    Driven by the red flags raised, by the findings of the report's sections
    (``findings``: an instrument carrying the rest, losers held longer, a
    weaker recent stretch, a thin cost margin) and by what the upload did not
    contain.
    Neutral wording: a question is something to ask, not an accusation, and
    the list never says whether to buy.

    An account history (``account_history``) is the live record itself and
    its prices are real fills, so the backtest questions (modelling, trials,
    held-out period, assumed costs) give way to the ones an investor needs.
    """
    wanted: set[str] = (
        {"other_accounts", "backtest_match"} if account_history else {"live_record", "modelling"}
    )
    for code in flag_codes:
        key = _FLAG_QUESTIONS.get(code)
        if key and not (account_history and key in _BACKTEST_ONLY):
            wanted.add(key)
    for finding in findings:
        key = _FINDING_QUESTIONS.get(finding)
        if key and not (account_history and key in _BACKTEST_ONLY):
            wanted.add(key)
    if "recent_period" in wanted:
        wanted.discard("recent_weaker")
    if not account_history:
        if not trials_measured:
            wanted.add("trials")
        if not has_out_of_sample:
            wanted.add("out_of_sample")
        if not has_costs:
            wanted.add("costs")
    if balance_only:
        wanted.add("equity_curve")
    if not has_trades:
        wanted.add("trades")
    months = LIVE_RECORD_MIN_MONTHS
    if min_track_record_months is not None and math.isfinite(min_track_record_months):
        months = max(LIVE_RECORD_MIN_MONTHS, int(math.ceil(min_track_record_months)))
    out: list[dict[str, str]] = []
    for key in _QUESTION_ORDER:
        if key in wanted:
            text = _QUESTIONS[key]
            if key == "live_record" and months > LIVE_RECORD_ASK_MONTHS:
                # Years of live history is not a fair ask: say what it would take instead.
                text = _QUESTIONS["live_record_long"]
            out.append(
                {
                    "code": key,
                    "es": text["es"].format(months=months),
                    "en": text["en"].format(months=months),
                }
            )
    return out


__all__ = [
    "CHALLENGE_ASSUMPTIONS",
    "DRAWDOWN_THRESHOLDS",
    "FAN_QUANTILES",
    "MAX_FAN_POINTS",
    "RISK_ASSUMPTIONS",
    "daily_returns_from_equity",
    "drawdown_risk",
    "simulate_challenge",
    "trade_statistics",
    "vendor_questions",
]
