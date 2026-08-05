"""Crypto-market quality checks for low/mid-cap OHLCV panels.

Implements the detectors designed in ``docs/CRYPTO_LOWCAP_ANTIBIAS_PLAN.md``:
wash-trading signatures, dead-but-listed tokens, phantom prints,
redenominations and ticker reuse. Every check reports its status explicitly —
``MEASURED`` with a finding count, or ``NOT_MEASURED`` with the reason (a
missing input column is a reason, never a zero). Findings are counted and
flagged; nothing here deletes or repairs data.

All numeric thresholds are ASSUMPTION-class evidence: declared module
constants, overridable per call, to be tuned against measured distributions
once the dataset exists. No unlabelled numbers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd

# --- ASSUMPTION-class thresholds (declared, overridable) ---------------------
#: A token whose close is identical for this many consecutive bars is treated
#: as dead-but-listed (daily bars: one week of frozen prices).
CONSTANT_CLOSE_MIN_RUN = 7
#: Identical nonzero volume repeated this many bars is quota-shaped reporting.
STALE_VOLUME_MIN_RUN = 5
#: Phantom print: at least this |return| on bottom-decile volume ...
SPIKE_REVERSAL_MIN_ABS_RETURN = 0.5
#: ... that retraces at least this fraction back to the pre-spike price.
SPIKE_REVERSAL_RETRACE = 0.8
#: "Low volume" for the spike check = at or below this quantile of the
#: symbol's positive volumes.
SPIKE_REVERSAL_VOLUME_QUANTILE = 0.10
#: Redenomination: overnight return at or below this while supply jumps.
REDENOMINATION_RETURN = -0.90
#: ... by at least this factor (or the inverse pair for reverse splits).
REDENOMINATION_SUPPLY_JUMP = 5.0
REDENOMINATION_INVERSE_RETURN = 9.0
#: Wash turnover: traded notional above this multiple of market cap ...
WASH_TURNOVER_RATIO = 1.0
#: ... sustained for at least this many consecutive bars.
WASH_TURNOVER_MIN_RUN = 5
#: Cap on symbols listed per finding, to keep reports readable.
MAX_AFFECTED_SYMBOLS = 20

STATUS_MEASURED = "MEASURED"
STATUS_NOT_MEASURED = "NOT_MEASURED"


@dataclass
class CryptoCheckResult:
    name: str
    status: str
    finding_count: int
    affected_symbols: list[str] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CryptoQualityReport:
    checks: list[CryptoCheckResult]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "checks": [check.to_dict() for check in self.checks],
            "warnings": list(self.warnings),
        }


def _sorted_groups(frame: pd.DataFrame) -> list[tuple[str, pd.DataFrame]]:
    if "symbol" in frame.columns:
        return [
            (str(key), group.sort_values("timestamp")) for key, group in frame.groupby("symbol")
        ]
    return [("", frame.sort_values("timestamp"))]


def _run_lengths(values: pd.Series) -> pd.DataFrame:
    """Sizes and first values of maximal runs of consecutive equal values."""
    run_id = (values != values.shift()).cumsum()
    grouped = values.groupby(run_id)
    return pd.DataFrame({"size": grouped.size(), "first": grouped.first()})


def _measured(name: str, per_symbol: dict[str, int]) -> CryptoCheckResult:
    affected = sorted(symbol for symbol, count in per_symbol.items() if count > 0)
    return CryptoCheckResult(
        name=name,
        status=STATUS_MEASURED,
        finding_count=int(sum(per_symbol.values())),
        affected_symbols=affected[:MAX_AFFECTED_SYMBOLS],
    )


def _not_measured(name: str, reason: str) -> CryptoCheckResult:
    return CryptoCheckResult(
        name=name, status=STATUS_NOT_MEASURED, finding_count=0, reason=reason
    )


def check_constant_price_runs(
    frame: pd.DataFrame, *, min_run: int = CONSTANT_CLOSE_MIN_RUN
) -> CryptoCheckResult:
    """Dead-but-listed: runs of >= min_run identical consecutive closes."""
    per_symbol: dict[str, int] = {}
    for symbol, group in _sorted_groups(frame):
        runs = _run_lengths(group["close"].astype(float))
        per_symbol[symbol] = int((runs["size"] >= min_run).sum())
    return _measured("constant_price_runs", per_symbol)


def check_zero_volume_price_moves(frame: pd.DataFrame) -> CryptoCheckResult:
    """Phantom by definition: the close moved on a bar with zero volume."""
    per_symbol: dict[str, int] = {}
    for symbol, group in _sorted_groups(frame):
        close = group["close"].astype(float)
        moved = close.diff().fillna(0.0) != 0.0
        zero_volume = group["volume"].astype(float) == 0.0
        per_symbol[symbol] = int((moved & zero_volume).sum())
    return _measured("zero_volume_price_moves", per_symbol)


def check_stale_volume_runs(
    frame: pd.DataFrame, *, min_run: int = STALE_VOLUME_MIN_RUN
) -> CryptoCheckResult:
    """Quota-shaped reporting: identical nonzero volume repeated >= min_run bars."""
    per_symbol: dict[str, int] = {}
    for symbol, group in _sorted_groups(frame):
        runs = _run_lengths(group["volume"].astype(float))
        per_symbol[symbol] = int(((runs["size"] >= min_run) & (runs["first"] > 0)).sum())
    return _measured("stale_volume_runs", per_symbol)


def check_volume_range_incoherence(frame: pd.DataFrame) -> CryptoCheckResult:
    """Above-median volume printed on bars with no price range at all.

    A single small trade legitimately prints high == low; heavy volume with
    zero range is the wash signature.
    """
    per_symbol: dict[str, int] = {}
    for symbol, group in _sorted_groups(frame):
        volume = group["volume"].astype(float)
        positive = volume[volume > 0]
        if positive.empty:
            per_symbol[symbol] = 0
            continue
        flat = group["high"].astype(float) == group["low"].astype(float)
        per_symbol[symbol] = int((flat & (volume > float(positive.median()))).sum())
    return _measured("volume_range_incoherence", per_symbol)


def check_spike_reversal_phantoms(
    frame: pd.DataFrame,
    *,
    min_abs_return: float = SPIKE_REVERSAL_MIN_ABS_RETURN,
    retrace: float = SPIKE_REVERSAL_RETRACE,
    volume_quantile: float = SPIKE_REVERSAL_VOLUME_QUANTILE,
) -> CryptoCheckResult:
    """Phantom print: a large move on bottom-quantile volume that the next bar
    retraces almost entirely — bid-ask bounce in an empty book."""
    per_symbol: dict[str, int] = {}
    for symbol, group in _sorted_groups(frame):
        close = group["close"].astype(float).reset_index(drop=True)
        volume = group["volume"].astype(float).reset_index(drop=True)
        if len(close) < 3:
            per_symbol[symbol] = 0
            continue
        positive = volume[volume > 0]
        low_volume_cut = float(positive.quantile(volume_quantile)) if not positive.empty else 0.0
        previous = close.shift(1)
        following = close.shift(-1)
        move = close - previous
        returns = close.pct_change()
        retraced = (following - previous).abs() <= (1.0 - retrace) * move.abs()
        flags = (
            (returns.abs() >= min_abs_return)
            & (volume <= low_volume_cut)
            & retraced.fillna(False)
        )
        per_symbol[symbol] = int(flags.fillna(False).sum())
    return _measured("spike_reversal_phantoms", per_symbol)


def check_redenominations(
    frame: pd.DataFrame,
    *,
    crash_return: float = REDENOMINATION_RETURN,
    supply_jump: float = REDENOMINATION_SUPPLY_JUMP,
    inverse_return: float = REDENOMINATION_INVERSE_RETURN,
) -> CryptoCheckResult:
    """Split/redenomination: a -90% "crash" (or +900% "pump") that is really a
    supply change — price and circulating supply jump by reciprocal factors.

    Requires a ``circulating_supply`` column; without it the check is
    NOT_MEASURED, not clean.
    """
    if "circulating_supply" not in frame.columns:
        return _not_measured("redenominations", "circulating_supply column absent")
    per_symbol: dict[str, int] = {}
    for symbol, group in _sorted_groups(frame):
        close = group["close"].astype(float)
        supply = group["circulating_supply"].astype(float)
        returns = close.pct_change()
        supply_ratio = supply / supply.shift(1)
        split = (returns <= crash_return) & (supply_ratio >= supply_jump)
        reverse = (returns >= inverse_return) & (supply_ratio <= 1.0 / supply_jump)
        per_symbol[symbol] = int((split | reverse).fillna(False).sum())
    return _measured("redenominations", per_symbol)


def check_wash_turnover(
    frame: pd.DataFrame,
    *,
    ratio: float = WASH_TURNOVER_RATIO,
    min_run: int = WASH_TURNOVER_MIN_RUN,
) -> CryptoCheckResult:
    """Sustained traded notional above ``ratio`` x market cap — presumptive wash
    for a low/mid-cap. Requires a ``market_cap`` column; else NOT_MEASURED."""
    if "market_cap" not in frame.columns:
        return _not_measured("wash_turnover", "market_cap column absent")
    per_symbol: dict[str, int] = {}
    for symbol, group in _sorted_groups(frame):
        market_cap = group["market_cap"].astype(float)
        notional = group["volume"].astype(float) * group["close"].astype(float)
        turnover = notional.where(market_cap > 0) / market_cap.where(market_cap > 0)
        exceeds = (turnover > ratio).fillna(False)
        run_id = (exceeds != exceeds.shift()).cumsum()
        run_size = exceeds.groupby(run_id).transform("size")
        per_symbol[symbol] = int((exceeds & (run_size >= min_run)).sum())
    return _measured("wash_turnover", per_symbol)


def check_ticker_reuse(universe: pd.DataFrame | None) -> CryptoCheckResult:
    """Identity welds: one symbol mapping to several coin ids (ticker reuse) or
    one coin id trading under several symbols over time (rename).

    Operates on a universe mapping frame with ``coin_id`` and ``symbol``
    columns (point-in-time snapshots provide it); without one the check is
    NOT_MEASURED.
    """
    if universe is None:
        return _not_measured("ticker_reuse", "universe mapping (coin_id, symbol) absent")
    missing = {"coin_id", "symbol"} - set(universe.columns)
    if missing:
        return _not_measured(
            "ticker_reuse", f"universe mapping lacks columns: {sorted(missing)}"
        )
    ids_per_symbol = universe.groupby("symbol")["coin_id"].nunique()
    reused = ids_per_symbol[ids_per_symbol > 1]
    symbols_per_id = universe.groupby("coin_id")["symbol"].nunique()
    renamed = symbols_per_id[symbols_per_id > 1]
    affected = sorted(str(s) for s in reused.index) + sorted(
        f"id:{i}" for i in renamed.index
    )
    return CryptoCheckResult(
        name="ticker_reuse",
        status=STATUS_MEASURED,
        finding_count=int(len(reused) + len(renamed)),
        affected_symbols=affected[:MAX_AFFECTED_SYMBOLS],
    )


def generate_crypto_quality_report(
    data: pd.DataFrame,
    universe: pd.DataFrame | None = None,
) -> CryptoQualityReport:
    """Run every crypto-market check and collect statuses and warnings.

    ``data`` is a canonical OHLCV frame (``timestamp, symbol, open, high,
    low, close, volume``) optionally carrying ``market_cap`` and
    ``circulating_supply`` columns; ``universe`` is an optional point-in-time
    mapping frame with ``coin_id`` and ``symbol``.
    """
    frame = data.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    checks = [
        check_constant_price_runs(frame),
        check_zero_volume_price_moves(frame),
        check_stale_volume_runs(frame),
        check_volume_range_incoherence(frame),
        check_spike_reversal_phantoms(frame),
        check_redenominations(frame),
        check_wash_turnover(frame),
        check_ticker_reuse(universe),
    ]
    warnings: list[str] = []
    for check in checks:
        if check.status == STATUS_NOT_MEASURED:
            warnings.append(
                f"{check.name} NOT_MEASURED ({check.reason}) — absence of a "
                "finding here is absence of measurement, not cleanliness"
            )
        elif check.finding_count:
            shown = ", ".join(check.affected_symbols)
            warnings.append(
                f"{check.name}: {check.finding_count} finding(s) in [{shown}]"
            )
    return CryptoQualityReport(checks=checks, warnings=warnings)
