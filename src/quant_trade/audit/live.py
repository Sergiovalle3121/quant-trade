"""Does a live account statement look like the backtest it came from?

A robot's buyer usually gets two files from its seller: the backtest and a
statement of a real (or demo) account running the robot. This module asks
one question of them: if the live trades had been drawn from the backtest's
own trades, how unusual would the live result be?

It resamples the backtest's closed trades (with replacement, as many as the
live statement holds) and places the live account's net result, hit rate
and deepest fall among those draws. A live result far below every draw says
the account is not behaving like the backtest; one far above says the two
files may not come from the same configuration. Nothing here forecasts a
future result: every figure is MEASURED from the two uploaded files.

Sizes: when the live account trades a different size (median volume more
than 25 % away from the backtest's), each live trade is rescaled to the
backtest's median size; otherwise both are compared as traded. Costs the files itemise per trade are
subtracted on both sides.

Same dates, trade by trade: where the two files cover the same days, each
live trade is paired with the backtest trade of the same side and symbol whose
entry is nearest and at most ``MATCH_WINDOW`` away. The share of live trades
found in the backtest says whether it is the same robot; the median price
difference at entry and exit (basis points, positive when worse for the
account) and the result difference of the paired trades, at the backtest
trade's size, measure what execution cost.

Limits: trades are resampled independently, so streaks and regime changes
in the backtest are not preserved; with fewer than ``MIN_LIVE_TRADES`` live
trades the comparison is not made. Pairing uses times as the files state
them: two files in different server time zones pair poorly.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

import numpy as np

from quant_trade.audit.schema import ParsedTrades, measured, not_measured

#: Fewer live trades than this say nothing about consistency.
MIN_LIVE_TRADES = 10
#: Fewer backtest trades than this make a poor pool to draw from.
MIN_BACKTEST_TRADES = 30
#: Resampled live histories drawn from the backtest.
SAMPLES = 5000
#: Cells (draws x trades) resampled at once, to bound memory.
CHUNK_CELLS = 1_000_000
#: Tail probabilities that separate the outcomes.
EDGE_TAIL = 0.05
OUT_TAIL = 0.01
#: A median size ratio outside this band rescales the live trades.
SIZE_BAND = (0.8, 1.25)
#: A live trading pace this far from the backtest's is worth a line.
PACE_BAND = (0.5, 2.0)

#: A live trade pairs with a backtest trade whose entry is at most this far.
MATCH_WINDOW = timedelta(minutes=60)
#: Fewer paired trades than this give no execution figures.
MIN_MATCHED = 5
#: Below this share of live trades found in the backtest, it may not be the same robot.
MATCH_LOW = 0.5

CONSISTENT = "CONSISTENT"
EDGE = "EDGE"
INCONSISTENT = "INCONSISTENT"
ABOVE = "ABOVE"

NOTE = (
    "Backtest trades resampled with replacement, as many as the live statement holds; "
    "costs itemised per trade subtracted on both sides. Streaks are not preserved."
)


PAIRING_NOTE = (
    "Paired by side, symbol and entry time within 60 minutes, as the files state the "
    "times; price differences in basis points (0.01 %), positive when worse for the "
    "account; result differences at the backtest trade's size."
)


def _net(parsed: ParsedTrades) -> np.ndarray:
    pnl = np.array([float(trade.pnl) for trade in parsed.trades], dtype=float)
    if parsed.fees is not None and len(parsed.fees) == len(pnl):
        pnl = pnl - np.array(parsed.fees, dtype=float)
    return pnl


def _sizes(parsed: ParsedTrades) -> np.ndarray:
    return np.array([float(trade.quantity) for trade in parsed.trades], dtype=float)


def _max_fall(pnl: np.ndarray) -> float:
    """Deepest fall of the running sum from its previous peak (0 or more)."""
    if pnl.size == 0:
        return 0.0
    path = np.concatenate(([0.0], np.cumsum(pnl)))
    return float(np.max(np.maximum.accumulate(path) - path))


def _months(start: datetime, end: datetime) -> float:
    return max((end - start).total_seconds() / (30.4375 * 86400), 1.0 / 30.4375)


def _side(pnl: np.ndarray, parsed: ParsedTrades) -> dict[str, Any]:
    trades = parsed.trades
    start = min(trade.entry_time for trade in trades)
    end = max(trade.exit_time for trade in trades)
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    return {
        "trades": measured(len(trades)),
        "start": start.date().isoformat(),
        "end": end.date().isoformat(),
        "per_month": measured(len(trades) / _months(start, end)),
        "net": measured(float(pnl.sum())),
        "mean": measured(float(pnl.mean())),
        "win_rate": measured(float((pnl > 0).mean())),
        "avg_win": measured(float(wins.mean())) if wins.size else None,
        "avg_loss": measured(float(losses.mean())) if losses.size else None,
        "max_fall": measured(_max_fall(pnl)),
    }


def _symbol(value: str) -> str:
    return "".join(ch for ch in value.upper() if ch.isalnum())


def _same_symbol(a: str, b: str) -> bool:
    """Symbols agree when either is unknown or one extends the other (EURUSD.m)."""
    a, b = _symbol(a), _symbol(b)
    return not a or not b or a.startswith(b) or b.startswith(a)


def _at(values: Sequence[str] | None, index: int) -> str:
    return values[index] if values and index < len(values) else ""


def _worse_bps(side: str, reference: float, actual: float, *, entry: bool) -> float:
    """Price difference in basis points, positive when worse for the account."""
    worse_when_higher = (side == "long") == entry
    diff = actual - reference if worse_when_higher else reference - actual
    return diff / reference * 10_000.0


def _pairing(
    backtest: ParsedTrades,
    live: ParsedTrades,
    bt_pnl: np.ndarray,
    live_pnl: np.ndarray,
    backtest_symbols: Sequence[str] | None,
    live_symbols: Sequence[str] | None,
) -> dict[str, Any] | None:
    """Live trades paired with backtest trades on the dates both files cover.

    ``bt_pnl`` and ``live_pnl`` are the net results as traded (not rescaled).
    Returns ``None`` when the files share no dates.
    """
    bt, lv = backtest.trades, live.trades
    start = max(min(t.entry_time for t in bt), min(t.entry_time for t in lv))
    end = min(max(t.entry_time for t in bt), max(t.entry_time for t in lv))
    if start > end:
        return None
    window = MATCH_WINDOW
    bt_idx = sorted(
        (i for i, t in enumerate(bt) if start - window <= t.entry_time <= end + window),
        key=lambda i: bt[i].entry_time,
    )
    live_idx = [i for i, t in enumerate(lv) if start <= t.entry_time <= end]
    bt_in = sum(1 for i in bt_idx if start <= bt[i].entry_time <= end)
    times = [bt[i].entry_time for i in bt_idx]
    pairs: list[tuple[int, int]] = []
    for j in sorted(live_idx, key=lambda k: (lv[k].entry_time, k)):
        when = lv[j].entry_time
        best: tuple[timedelta, int] | None = None
        for pos in range(bisect_left(times, when - window), len(times)):
            if times[pos] > when + window:
                break
            if best is not None and times[pos] - when >= best[0]:
                break  # later entries are only further away
            i = bt_idx[pos]
            if backtest.sides[i] != live.sides[j]:
                continue
            if not _same_symbol(_at(backtest_symbols, i), _at(live_symbols, j)):
                continue
            gap = abs(times[pos] - when)
            if best is None or gap < best[0]:
                best = (gap, pos)
        if best is not None:
            # A paired backtest trade leaves the candidates, so thousands of
            # trades opened in the same hour are not scanned again and again.
            pairs.append((bt_idx.pop(best[1]), j))
            del times[best[1]]
    out: dict[str, Any] = {
        "status": "MEASURED",
        "note": PAIRING_NOTE,
        "start": start.date().isoformat(),
        "end": end.date().isoformat(),
        "backtest_trades": measured(bt_in),
        "live_trades": measured(len(live_idx)),
        "matched": measured(len(pairs)),
        "matched_share": (
            measured(len(pairs) / len(live_idx), "paired live trades / live trades")
            if live_idx
            else not_measured("no live trades on the shared dates")
        ),
        "missing_live": measured(max(bt_in - len(pairs), 0)),
        "low_match": bool(len(live_idx) >= MIN_MATCHED and len(pairs) / len(live_idx) < MATCH_LOW),
    }
    priced = [
        (i, j)
        for i, j in pairs
        if bt[i].entry_price > 0 and bt[i].exit_price > 0 and lv[j].quantity > 0
    ]
    if len(priced) < MIN_MATCHED:
        reason = f"fewer than {MIN_MATCHED} paired trades"
        out["entry_bps"] = not_measured(reason)
        out["exit_bps"] = not_measured(reason)
        out["result_gap"] = not_measured(reason)
        return out
    entry = [
        _worse_bps(live.sides[j], bt[i].entry_price, lv[j].entry_price, entry=True)
        for i, j in priced
    ]
    exit_ = [
        _worse_bps(live.sides[j], bt[i].exit_price, lv[j].exit_price, entry=False)
        for i, j in priced
    ]
    gaps = [
        float(live_pnl[j]) * bt[i].quantity / lv[j].quantity - float(bt_pnl[i]) for i, j in priced
    ]
    out["entry_bps"] = measured(float(np.median(entry)))
    out["exit_bps"] = measured(float(np.median(exit_)))
    out["result_gap"] = measured(float(np.sum(gaps)))
    out["result_gap_per_trade"] = measured(float(np.mean(gaps)))
    return out


def _resample(
    pool: np.ndarray, length: int, *, samples: int, seed: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Net result, hit rate and deepest fall of ``samples`` resampled histories.

    Drawn in chunks so a long live statement never holds every path in memory.
    """
    rng = np.random.default_rng(seed)
    chunk = max(1, min(samples, CHUNK_CELLS // max(length, 1)))
    nets, hits, falls = [], [], []
    for start in range(0, samples, chunk):
        size = min(chunk, samples - start)
        draws = pool[rng.integers(0, pool.size, size=(size, length))]
        paths = np.concatenate((np.zeros((size, 1)), np.cumsum(draws, axis=1)), axis=1)
        nets.append(paths[:, -1])
        hits.append((draws > 0).mean(axis=1))
        falls.append(np.max(np.maximum.accumulate(paths, axis=1) - paths, axis=1))
    return np.concatenate(nets), np.concatenate(hits), np.concatenate(falls)


def _band(values: np.ndarray) -> dict[str, float]:
    return {"p5": float(np.quantile(values, 0.05)), "p95": float(np.quantile(values, 0.95))}


def _outcome(net_below: float, net_above: float, fall_above: float) -> str:
    """The comparison's outcome from the live figures' tail probabilities.

    ``net_below``: share of draws at or below the live net result;
    ``net_above``: share at or above it; ``fall_above``: share of draws with a
    fall at least as deep as the live one.
    """
    if net_below < OUT_TAIL or fall_above < OUT_TAIL:
        return INCONSISTENT
    if net_below < EDGE_TAIL or fall_above < EDGE_TAIL:
        return EDGE
    if net_above < OUT_TAIL:
        return ABOVE
    return CONSISTENT


def compare_live(
    backtest: ParsedTrades | None,
    live: ParsedTrades,
    *,
    backtest_symbols: Sequence[str] | None = None,
    live_symbols: Sequence[str] | None = None,
    samples: int = SAMPLES,
    seed: int = 12345,
) -> dict[str, Any]:
    """Place a live statement's trades among resampled backtest histories."""
    if backtest is None or not backtest.trades:
        return {"status": "NOT_MEASURED", "reason": "the backtest has no closed trades"}
    if len(backtest.trades) < MIN_BACKTEST_TRADES:
        return {
            "status": "NOT_MEASURED",
            "reason": f"the backtest has fewer than {MIN_BACKTEST_TRADES} closed trades",
        }
    if len(live.trades) < MIN_LIVE_TRADES:
        return {
            "status": "NOT_MEASURED",
            "reason": f"the live statement has fewer than {MIN_LIVE_TRADES} closed trades",
        }
    bt_pnl, live_pnl = _net(backtest), _net(live)
    as_traded = live_pnl
    bt_size, live_size = _sizes(backtest), _sizes(live)
    size_ratio = float(np.median(live_size) / np.median(bt_size))
    rescaled = not (SIZE_BAND[0] <= size_ratio <= SIZE_BAND[1])
    if rescaled:
        live_pnl = live_pnl * float(np.median(bt_size)) / live_size

    nets, hits, falls = _resample(bt_pnl, live_pnl.size, samples=samples, seed=seed)

    live_net = float(live_pnl.sum())
    live_fall = _max_fall(live_pnl)
    net_below = float((nets <= live_net).mean())
    net_above = float((nets >= live_net).mean())
    fall_above = float((falls >= live_fall).mean())
    method = f"{samples} resampled histories of {live_pnl.size} backtest trades, seed {seed}"

    backtest_side = _side(bt_pnl, backtest)
    live_side = _side(live_pnl, live)
    pace = live_side["per_month"]["value"] / backtest_side["per_month"]["value"]
    known = {_symbol(s) for s in backtest_symbols or () if _symbol(s)}
    new_symbols = sorted(
        {
            s.strip()
            for s in live_symbols or ()
            if _symbol(s) and not any(_same_symbol(s, b) for b in known)
        }
    )
    pairing = _pairing(backtest, live, bt_pnl, as_traded, backtest_symbols, live_symbols)
    return {
        "status": "MEASURED",
        "note": NOTE,
        "outcome": _outcome(net_below, net_above, fall_above),
        "rescaled": rescaled,
        "size_ratio": measured(size_ratio),
        "backtest": backtest_side,
        "live": live_side,
        "expected": {
            "net": _band(nets),
            "win_rate": _band(hits),
            "max_fall": _band(falls),
        },
        "net_below": measured(net_below, method),
        "fall_above": measured(fall_above, method),
        "pace_ratio": measured(pace),
        "pace_differs": not (PACE_BAND[0] <= pace <= PACE_BAND[1]),
        "overlap": live_side["start"] <= backtest_side["end"],
        "new_symbols": new_symbols[:10] if backtest_symbols and live_symbols else [],
        "pairing": pairing,
        "samples": samples,
        "seed": seed,
    }


__all__ = ["MIN_LIVE_TRADES", "compare_live"]
