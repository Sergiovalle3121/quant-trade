"""Red flags: what a return series looks like when something went wrong.

None of these prove misconduct. Each is a pattern that appears far more often
in backtests with a bug, a look-ahead, or a marking problem than in honest
ones, so a hit is a question the client should answer before the number is
trusted. Severity ``FAIL`` means the audit cannot stand behind the headline
numbers; ``WARN`` means the number is reported with the caveat attached.

Thresholds are constants here, recorded in the report, and covered by tests
one code at a time. Changing one is a documented decision, not a tweak.
"""

from __future__ import annotations

import bisect
import heapq
import math
from dataclasses import asdict, dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd

from quant_trade.audit.schema import (
    MIN_OBSERVATIONS,
    DeclaredMetadata,
    IngestedSeries,
    ParsedTrades,
    printed_step,
)
from quant_trade.core.models import Trade

Severity = Literal["FAIL", "WARN"]

#: Same constants as ``data/quality/report.py``; the fat-finger signature is
#: the same whether the series is a price or an equity curve.
SPIKE_ROBUST_Z = 10.0
SPIKE_MIN_ABS_RETURN = 0.15

OBSERVATIONS_WARN = 100
UNPARSEABLE_FAIL_SHARE = 0.05
STALE_RUN_WARN = 5
STALE_RUN_FAIL = 20
SPIKES_FAIL = 4
#: Annualised Sharpe above which a retail backtest is more likely mis-measured
#: than exceptional. Intraday series legitimately reach higher ratios.
SHARPE_WARN_DAILY = 3.0
SHARPE_FAIL_DAILY = 6.0
SHARPE_WARN_INTRADAY = 6.0
SHARPE_FAIL_INTRADAY = 10.0
INTRADAY_PERIODS_PER_YEAR = 400.0
GAP_MULTIPLE = 10.0
PNL_MISMATCH_SHARE = 0.01


@dataclass(frozen=True)
class RedFlag:
    code: str
    severity: Severity
    detail: str
    value: float | int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect_mad_spikes(
    returns: pd.Series,
    *,
    robust_z: float = SPIKE_ROBUST_Z,
    min_abs: float = SPIKE_MIN_ABS_RETURN,
) -> int:
    """Count returns that are extreme outliers against the series' own
    distribution (robust MAD z-score) and large in absolute terms."""
    clean = pd.to_numeric(returns, errors="coerce").dropna()
    if len(clean) < 10:
        return 0
    median = clean.median()
    mad = (clean - median).abs().median()
    if mad <= 0:
        return int((clean.abs() > min_abs).sum())
    z = (clean - median).abs() / (1.4826 * mad)
    return int(((z > robust_z) & (clean.abs() > min_abs)).sum())


def longest_stale_run(returns: pd.Series) -> int:
    """Longest run of identical consecutive non-zero returns.

    Zero returns are excluded: a strategy sitting in cash produces exact
    zeros honestly. Identical non-zero returns repeated for days are a
    forward-fill or a mark-to-model.
    """
    values = pd.to_numeric(returns, errors="coerce").dropna().to_numpy(dtype=float)
    longest = 0
    run = 0
    for index in range(1, len(values)):
        same = math.isclose(values[index], values[index - 1], rel_tol=1e-9, abs_tol=1e-12)
        if values[index] != 0.0 and same:
            run = run + 1 if run else 2
            longest = max(longest, run)
        else:
            run = 0
    return longest


def annualised_sharpe(returns: pd.Series, periods_per_year: float) -> float:
    clean = pd.to_numeric(returns, errors="coerce").dropna()
    if len(clean) < 3:
        return 0.0
    std = float(clean.std(ddof=1))
    if std <= 0:
        return 0.0
    return float(clean.mean() / std * np.sqrt(periods_per_year))


def scan(
    series: IngestedSeries,
    *,
    periods_per_year: float,
    declared: DeclaredMetadata,
    trades: ParsedTrades | None = None,
    recomputed_pnl: list[float] | None = None,
    variants_columns: int = 0,
    real_fills: bool = False,
) -> list[RedFlag]:
    flags: list[RedFlag] = []
    frame = series.frame
    returns = series.returns
    n = int(len(returns))

    if n < MIN_OBSERVATIONS:
        flags.append(
            RedFlag(
                "TOO_FEW_OBSERVATIONS",
                "FAIL",
                f"{n} return observations; at least {MIN_OBSERVATIONS} are needed",
                n,
            )
        )
    elif n < OBSERVATIONS_WARN:
        flags.append(
            RedFlag(
                "TOO_FEW_OBSERVATIONS",
                "WARN",
                f"{n} return observations; conclusions below {OBSERVATIONS_WARN} are fragile",
                n,
            )
        )

    non_positive = int((frame["equity"] <= 0).sum())
    if non_positive:
        flags.append(
            RedFlag(
                "NON_POSITIVE_EQUITY",
                "FAIL",
                f"{non_positive} equity value(s) at or below zero; returns are undefined there",
                non_positive,
            )
        )

    if series.duplicate_timestamps:
        flags.append(
            RedFlag(
                "DUPLICATE_TIMESTAMPS",
                "FAIL",
                f"{series.duplicate_timestamps} duplicated timestamp(s); the last value was kept",
                series.duplicate_timestamps,
            )
        )
    if series.non_monotonic:
        flags.append(
            RedFlag(
                "NON_MONOTONIC_TIMESTAMPS",
                "WARN",
                "rows were not in chronological order; sorted before analysis",
            )
        )
    if series.unparseable_rows:
        share = series.unparseable_rows / max(series.raw_rows, 1)
        flags.append(
            RedFlag(
                "UNPARSEABLE_ROWS",
                "FAIL" if share > UNPARSEABLE_FAIL_SHARE else "WARN",
                f"{series.unparseable_rows} of {series.raw_rows} rows could not be read",
                series.unparseable_rows,
            )
        )

    std = float(returns.std(ddof=1)) if n >= 2 else 0.0
    if n >= 2 and std <= 0:
        flags.append(
            RedFlag("ZERO_VARIANCE", "FAIL", "every return is identical; nothing to measure")
        )

    stale = longest_stale_run(returns)
    if stale >= STALE_RUN_FAIL:
        flags.append(
            RedFlag(
                "STALE_MARKS",
                "FAIL",
                f"{stale} consecutive identical non-zero returns; looks forward-filled",
                stale,
            )
        )
    elif stale >= STALE_RUN_WARN:
        flags.append(
            RedFlag(
                "STALE_MARKS",
                "WARN",
                f"{stale} consecutive identical non-zero returns",
                stale,
            )
        )

    spikes = detect_mad_spikes(returns)
    if spikes >= SPIKES_FAIL:
        flags.append(
            RedFlag(
                "MAD_SPIKES",
                "FAIL",
                f"{spikes} single-period moves are extreme outliers (>{SPIKE_MIN_ABS_RETURN:.0%} "
                f"and >{SPIKE_ROBUST_Z:g} robust sigmas)",
                spikes,
            )
        )
    elif spikes >= 1:
        flags.append(
            RedFlag(
                "MAD_SPIKES",
                "WARN",
                f"{spikes} single-period move(s) are extreme outliers; check for bad prints",
                spikes,
            )
        )

    sharpe = annualised_sharpe(returns, periods_per_year)
    intraday = periods_per_year > INTRADAY_PERIODS_PER_YEAR
    warn_at = SHARPE_WARN_INTRADAY if intraday else SHARPE_WARN_DAILY
    fail_at = SHARPE_FAIL_INTRADAY if intraday else SHARPE_FAIL_DAILY
    if sharpe > fail_at:
        flags.append(
            RedFlag(
                "IMPLAUSIBLE_SHARPE",
                "FAIL",
                f"annualised Sharpe {sharpe:.2f} exceeds {fail_at:g}; almost always a look-ahead "
                "or a costless fill assumption",
                sharpe,
            )
        )
    elif sharpe > warn_at:
        flags.append(
            RedFlag(
                "IMPLAUSIBLE_SHARPE",
                "WARN",
                f"annualised Sharpe {sharpe:.2f} exceeds {warn_at:g}; rare outside intraday "
                "market making",
                sharpe,
            )
        )

    spacing = frame["timestamp"].diff().dropna()
    if len(spacing) >= 2:
        median = spacing.median()
        if median > pd.Timedelta(0):
            multiple = float(spacing.max() / median)
            if multiple > GAP_MULTIPLE:
                flags.append(
                    RedFlag(
                        "LARGE_GAPS",
                        "WARN",
                        f"largest gap between rows is {multiple:.0f}x the median spacing",
                        multiple,
                    )
                )

    # A report that itemises commission and fees has measured costs even
    # when the client declares none, and so has an account history: its
    # prices are the broker's real fills.
    if (
        declared.cost_bps_per_side == 0
        and not real_fills
        and not (trades is not None and trades.reports_fees)
    ):
        flags.append(
            RedFlag(
                "ZERO_DECLARED_COSTS",
                "WARN",
                "no trading cost declared; the cost dimension uses a reference assumption",
            )
        )
    if variants_columns and declared.trials_declared and declared.trials < variants_columns:
        flags.append(
            RedFlag(
                "TRIALS_BELOW_VARIANTS",
                "WARN",
                f"{declared.trials} trial(s) declared but the files show {variants_columns} "
                "variants or optimisation passes; the declared count is too low",
                variants_columns,
            )
        )

    if trades is not None:
        if trades.invalid_rows:
            flags.append(
                RedFlag(
                    "INVALID_TRADE_ROWS",
                    "WARN",
                    f"{trades.invalid_rows} trade row(s) dropped as unreadable",
                    trades.invalid_rows,
                )
            )
        if recomputed_pnl is not None:
            reported = [
                (client, ours)
                for client, ours in zip(trades.client_pnl, recomputed_pnl, strict=True)
                if client is not None
            ]
            if reported:
                gross = sum(abs(ours) for _, ours in reported)
                # A difference within half the file's printed precision is rounding.
                mismatch = sum(
                    max(abs(client - ours) - printed_step(client) / 2, 0.0)
                    for client, ours in reported
                )
                if gross > 0 and mismatch / gross > PNL_MISMATCH_SHARE:
                    flags.append(
                        RedFlag(
                            "TRADE_PNL_MISMATCH",
                            "WARN",
                            f"client-reported pnl differs from recomputed pnl by "
                            f"{mismatch / gross:.1%} of gross; the trades file may carry "
                            "costs or a different contract size",
                            mismatch / gross,
                        )
                    )
    return flags


# ---------------------------------------------------------------------------
# Trade-level patterns: martingale, grid, averaging down, missing stops
# ---------------------------------------------------------------------------

#: Median size of trades after a loss over the median after a win. 1.25x
#: warns, 1.6x (with most post-loss trades larger than the loss) fails:
#: growing size after losses is the martingale signature.
MARTINGALE_WARN_RATIO = 1.25
MARTINGALE_FAIL_RATIO = 1.6
MARTINGALE_FAIL_INCREASE_SHARE = 0.6
MARTINGALE_MIN_EACH = 5
#: Share of trades opened while a same-direction position on the same symbol
#: was open at a better price.
GRID_WARN_SHARE = 0.2
GRID_WARN_MIN = 5
GRID_FAIL_SHARE = 0.4
GRID_FAIL_MIN = 10
CONCURRENT_WARN = 5
HIGH_WINRATE = 0.85
HIGH_WINRATE_LOSS_MULTIPLE = 3.0
HIGH_WINRATE_MIN_TRADES = 20
#: Largest loss (or adverse excursion) over the mean loss.
NO_STOP_LOSS_MULTIPLE = 8.0
NO_STOP_MIN_LOSSES = 10


def _martingale(
    order: list[int], trades: list[Trade], pnl: list[float]
) -> tuple[float, float, int, int]:
    """Median size of trades that follow a loss over the median size of
    trades that follow a win, and the share of post-loss trades larger than
    the losing trade. The previous outcome of a trade is the last trade
    closed at or before its entry."""
    after_loss: list[float] = []
    after_win: list[float] = []
    larger_after_loss: list[bool] = []
    closed = sorted(order, key=lambda i: (trades[i].exit_time, i))
    exits = [trades[i].exit_time for i in closed]
    for i in order:
        position = bisect.bisect_right(exits, trades[i].entry_time) - 1
        if position < 0:
            continue
        previous = closed[position]
        if previous == i:
            continue
        size = trades[i].quantity
        if pnl[previous] < 0:
            after_loss.append(size)
            larger_after_loss.append(size > trades[previous].quantity * (1 + 1e-9))
        elif pnl[previous] > 0:
            after_win.append(size)
    if len(after_loss) < MARTINGALE_MIN_EACH or len(after_win) < MARTINGALE_MIN_EACH:
        return 1.0, 0.0, len(after_loss), len(after_win)
    ratio = float(np.median(after_loss) / np.median(after_win))
    increase_share = float(np.mean(larger_after_loss))
    return ratio, increase_share, len(after_loss), len(after_win)


def _grid_and_concurrency(
    order: list[int], trades: list[Trade], sides: list[str], symbols: list[str]
) -> tuple[int, int]:
    """Trades added against the position (same symbol and side, worse
    price, while an earlier one is open) and the most positions open at
    once on one symbol.

    One sweep in entry order (``order`` sorted by entry time, then index):
    a trade that has closed by the time a later one enters stays closed for
    every trade after it, so closed trades are dropped lazily from heaps
    keyed by exit time and, per symbol and side, by entry price. That keeps
    a 50 000-trade upload to well under a second instead of a quadratic
    scan measured in minutes.
    """
    adds = 0
    most = 0
    # Per symbol: exit times of the trades entered so far that are still open.
    open_exits: dict[str, list[Any]] = {}
    # Per (symbol, side): the open trade with the worst price for a new
    # entry on top (highest entry for longs, lowest for shorts).
    best_price: dict[tuple[str, str], list[tuple[float, Any]]] = {}
    for i in order:
        trade = trades[i]
        now = trade.entry_time
        exits = open_exits.setdefault(symbols[i], [])
        while exits and exits[0] <= now:
            heapq.heappop(exits)
        most = max(most, len(exits) + 1)
        key = (symbols[i], sides[i])
        prices = best_price.setdefault(key, [])
        while prices and prices[0][1] <= now:
            heapq.heappop(prices)
        if prices:
            top = -prices[0][0] if sides[i] == "long" else prices[0][0]
            worse = trade.entry_price < top if sides[i] == "long" else trade.entry_price > top
            if worse:
                adds += 1
        heapq.heappush(exits, trade.exit_time)
        signed = -trade.entry_price if sides[i] == "long" else trade.entry_price
        heapq.heappush(prices, (signed, trade.exit_time))
    return adds, most


def scan_trade_patterns(
    trades: ParsedTrades,
    *,
    symbols: list[str] | None = None,
    adverse_excursion: list[float | None] | None = None,
    balance_only: bool = False,
) -> list[RedFlag]:
    """Sizing and position patterns that hide risk from a balance curve.

    Martingale sizing (larger after losses), grid or averaging down (adding
    against an open position at worse prices), many positions open at once,
    a high win rate paid for by rare large losses, and losses far beyond the
    typical one (no evidence of a stop). ``symbols`` defaults to a single
    instrument; ``adverse_excursion`` (per-trade maximum adverse excursion
    in account currency, positive) is used when a report carries it; with
    ``balance_only`` a curve rebuilt from closed trades that overlap is
    flagged because floating losses are invisible in it. None of these
    proves the strategy is a martingale or grid; each is a question to ask.
    """
    items = trades.trades
    n = len(items)
    if n == 0:
        return []
    sides = list(trades.sides)
    names = list(symbols) if symbols is not None else ["*"] * n
    if len(names) != n or len(sides) != n:
        raise ValueError("symbols and sides must match the number of trades")
    pnl = [trade.pnl for trade in items]
    order = sorted(range(n), key=lambda i: (items[i].entry_time, i))
    flags: list[RedFlag] = []

    ratio, increase_share, n_loss, n_win = _martingale(order, items, pnl)
    if ratio >= MARTINGALE_FAIL_RATIO and increase_share >= MARTINGALE_FAIL_INCREASE_SHARE:
        flags.append(
            RedFlag(
                "MARTINGALE_SIZING",
                "FAIL",
                f"after a loss the next trade is typically {ratio:.2f}x the size used after a "
                f"win, and {increase_share:.0%} of post-loss trades were larger "
                f"({n_loss} after losses, {n_win} after wins)",
                ratio,
            )
        )
    elif ratio >= MARTINGALE_WARN_RATIO:
        flags.append(
            RedFlag(
                "MARTINGALE_SIZING",
                "WARN",
                f"after a loss the next trade is typically {ratio:.2f}x the size used after a win",
                ratio,
            )
        )

    adds, most = _grid_and_concurrency(order, items, sides, names)
    share = adds / n
    if adds >= GRID_FAIL_MIN and share >= GRID_FAIL_SHARE:
        flags.append(
            RedFlag(
                "GRID_AVERAGING",
                "FAIL",
                f"{adds} of {n} trades ({share:.0%}) were opened against an open position at a "
                "worse price: grid or averaging down",
                share,
            )
        )
    elif adds >= GRID_WARN_MIN and share >= GRID_WARN_SHARE:
        flags.append(
            RedFlag(
                "GRID_AVERAGING",
                "WARN",
                f"{adds} of {n} trades ({share:.0%}) were opened against an open position at a "
                "worse price",
                share,
            )
        )
    if most >= CONCURRENT_WARN:
        flags.append(
            RedFlag(
                "MANY_CONCURRENT_POSITIONS",
                "WARN",
                f"up to {most} positions were open at once on one symbol",
                most,
            )
        )
    if balance_only and most >= 2:
        flags.append(
            RedFlag(
                "HIDDEN_FLOATING_DRAWDOWN",
                "WARN",
                "the curve is rebuilt from closed trades while positions overlapped; floating "
                "losses of open positions are not visible in it",
                most,
            )
        )

    wins = [value for value in pnl if value > 0]
    losses = [-value for value in pnl if value < 0]
    if n >= HIGH_WINRATE_MIN_TRADES and wins and losses:
        win_rate = len(wins) / n
        multiple = float(np.mean(losses) / np.mean(wins))
        if win_rate > HIGH_WINRATE and multiple >= HIGH_WINRATE_LOSS_MULTIPLE:
            flags.append(
                RedFlag(
                    "NEGATIVE_PAYOFF_HIGH_WINRATE",
                    "WARN",
                    f"win rate {win_rate:.0%} with the average loss {multiple:.1f}x the average "
                    "win: rare large losses carry the risk",
                    multiple,
                )
            )
    if len(losses) >= NO_STOP_MIN_LOSSES:
        typical = float(np.mean(losses))
        excursions = [abs(v) for v in (adverse_excursion or []) if v is not None]
        worst = max([max(losses), *excursions])
        if typical > 0 and worst / typical >= NO_STOP_LOSS_MULTIPLE:
            from_excursion = bool(excursions) and max(excursions) >= max(losses)
            source = "adverse excursion" if from_excursion else "loss"
            flags.append(
                RedFlag(
                    "NO_STOP_EVIDENCE",
                    "WARN",
                    f"the largest {source} is {worst / typical:.1f}x the average loss; no sign of "
                    "a fixed stop",
                    worst / typical,
                )
            )
    return flags


# ---------------------------------------------------------------------------
# Trades against the equity curve
# ---------------------------------------------------------------------------

#: Share of trade exits that may fall outside the equity curve's dates.
TRADES_OUTSIDE_WARN_SHARE = 0.10
#: Months with trade exits needed before the monthly comparison is made.
TRADES_EQUITY_MIN_MONTHS = 6
#: Correlation between monthly realised trade pnl and monthly equity change
#: below which the two files do not look like the same account.
TRADES_EQUITY_MIN_CORRELATION = 0.2


def scan_trades_against_equity(trades: ParsedTrades, frame: pd.DataFrame) -> list[RedFlag]:
    """Do the uploaded trades and the uploaded equity curve describe the same
    account? Two cheap checks: the trades close inside the curve's dates, and
    month by month the realised trade pnl moves with the curve. A curve that
    marks open positions daily still moves with its realised pnl over a month,
    so a correlation near zero means the files are unrelated or one of them
    is wrong. Skipped when the curve was rebuilt from the same trades."""
    items = trades.trades
    if not items or len(frame) < 2:
        return []
    stamps = pd.to_datetime(frame["timestamp"], utc=True)
    first = stamps.iloc[0] - pd.Timedelta(days=1)
    last = stamps.iloc[-1] + pd.Timedelta(days=1)
    exits = pd.to_datetime(pd.Series([trade.exit_time for trade in items]), utc=True)
    outside = int(((exits < first) | (exits > last)).sum())
    flags: list[RedFlag] = []
    share = outside / len(items)
    if share > TRADES_OUTSIDE_WARN_SHARE:
        flags.append(
            RedFlag(
                "TRADES_OUTSIDE_EQUITY",
                "WARN",
                f"{outside} of {len(items)} trades ({share:.0%}) close outside the dates of the "
                "equity curve; the two files may not describe the same account",
                share,
            )
        )
    inside = (exits >= first) & (exits <= last)
    pnl = pd.Series([trade.pnl for trade in items], dtype=float)[inside.to_numpy()]
    if pnl.empty:
        return flags
    month_of_exit = exits[inside].dt.year.to_numpy() * 12 + exits[inside].dt.month.to_numpy()
    realised = pnl.groupby(month_of_exit).sum()
    equity = pd.Series(frame["equity"].to_numpy(dtype=float))
    month_of_row = stamps.dt.year.to_numpy() * 12 + stamps.dt.month.to_numpy()
    month_end = equity.groupby(month_of_row).last()
    change = month_end.diff()
    change.iloc[0] = month_end.iloc[0] - float(equity.iloc[0])
    joined = pd.concat([realised.rename("pnl"), change.rename("equity")], axis=1).dropna()
    joined = joined[joined["pnl"] != 0]
    if len(joined) < TRADES_EQUITY_MIN_MONTHS:
        return flags
    if float(joined["pnl"].std()) <= 0 or float(joined["equity"].std()) <= 0:
        return flags
    correlation = float(joined["pnl"].corr(joined["equity"]))
    if math.isfinite(correlation) and correlation < TRADES_EQUITY_MIN_CORRELATION:
        flags.append(
            RedFlag(
                "TRADES_EQUITY_UNRELATED",
                "WARN",
                f"month by month the realised trade pnl and the equity change correlate at "
                f"{correlation:.2f} over {len(joined)} months; the trades may not belong to "
                "this equity curve, so the cost dimension may not describe it",
                correlation,
            )
        )
    return flags


#: Short names of every red flag, for readers of the report.
FLAG_TITLES: dict[str, dict[str, str]] = {
    "TOO_FEW_OBSERVATIONS": {
        "es": "Muy pocas observaciones",
        "en": "Too few observations",
    },
    "NON_POSITIVE_EQUITY": {"es": "Equity en cero o negativa", "en": "Zero or negative equity"},
    "DUPLICATE_TIMESTAMPS": {"es": "Fechas duplicadas", "en": "Duplicated timestamps"},
    "NON_MONOTONIC_TIMESTAMPS": {"es": "Fechas desordenadas", "en": "Timestamps out of order"},
    "UNPARSEABLE_ROWS": {"es": "Filas ilegibles", "en": "Unreadable rows"},
    "ZERO_VARIANCE": {"es": "Retornos sin variación", "en": "Returns without variation"},
    "STALE_MARKS": {"es": "Valores congelados", "en": "Frozen marks"},
    "MAD_SPIKES": {"es": "Saltos extremos", "en": "Extreme jumps"},
    "IMPLAUSIBLE_SHARPE": {"es": "Sharpe inverosímil", "en": "Implausible Sharpe ratio"},
    "LARGE_GAPS": {"es": "Huecos grandes entre filas", "en": "Large gaps between rows"},
    "ZERO_DECLARED_COSTS": {"es": "Costes declarados en cero", "en": "Zero declared costs"},
    "TRIALS_BELOW_VARIANTS": {
        "es": "Menos intentos declarados que los que muestran los archivos",
        "en": "Fewer trials declared than the files show",
    },
    "INVALID_TRADE_ROWS": {"es": "Operaciones ilegibles", "en": "Unreadable trades"},
    "TRADE_PNL_MISMATCH": {
        "es": "El resultado declarado por operación no cuadra",
        "en": "Reported per-trade result does not match",
    },
    "MARTINGALE_SIZING": {
        "es": "Tamaño que crece tras pérdidas (martingala)",
        "en": "Size grows after losses (martingale)",
    },
    "GRID_AVERAGING": {
        "es": "Rejilla o promediar pérdidas",
        "en": "Grid or averaging down",
    },
    "MANY_CONCURRENT_POSITIONS": {
        "es": "Muchas posiciones abiertas a la vez",
        "en": "Many positions open at once",
    },
    "HIDDEN_FLOATING_DRAWDOWN": {
        "es": "Drawdown flotante oculto",
        "en": "Hidden floating drawdown",
    },
    "NEGATIVE_PAYOFF_HIGH_WINRATE": {
        "es": "Muchos aciertos pequeños y pérdidas grandes",
        "en": "Many small wins and large losses",
    },
    "NO_STOP_EVIDENCE": {"es": "Sin señal de stop de pérdida", "en": "No sign of a stop loss"},
    "TRADES_OUTSIDE_EQUITY": {
        "es": "Operaciones fuera de las fechas de la curva",
        "en": "Trades outside the curve's dates",
    },
    "TRADES_EQUITY_UNRELATED": {
        "es": "Operaciones que no se mueven con la curva",
        "en": "Trades that do not move with the curve",
    },
    "GAIN_INFLATED_BY_FLOWS": {
        "es": "El % de ganancia no refleja el dinero",
        "en": "The percentage gain does not reflect the money",
    },
    "DEPOSIT_DURING_DRAWDOWN": {
        "es": "Depósitos en plena pérdida",
        "en": "Deposits in a deep drawdown",
    },
    "FLOATING_LOSS_AT_END": {
        "es": "Pérdida abierta que el balance no muestra",
        "en": "Open loss the balance does not show",
    },
    "COARSE_TICK_MODEL": {
        "es": "Backtest con un modelado de precios grueso",
        "en": "Backtest run on a coarse price model",
    },
    "TEST_DATA_QUALITY_LOW": {
        "es": "Historial de precios incompleto en la prueba",
        "en": "Incomplete price history in the test",
    },
    "ISOLATED_OPTIMUM": {
        "es": "Parámetros en un pico aislado",
        "en": "Settings on a lone peak",
    },
    "REPORT_HEADER_MISMATCH": {
        "es": "El encabezado del informe no cuadra",
        "en": "The report header does not add up",
    },
}


def flag_title(code: str, locale: str) -> str:
    """A reader's name for a flag code; the code itself when unknown."""
    titles = FLAG_TITLES.get(code)
    if titles is None:
        return code
    return titles.get(locale, titles["en"])


__all__ = [
    "FLAG_TITLES",
    "RedFlag",
    "Severity",
    "annualised_sharpe",
    "detect_mad_spikes",
    "longest_stale_run",
    "flag_title",
    "scan",
    "scan_trade_patterns",
    "scan_trades_against_equity",
]
