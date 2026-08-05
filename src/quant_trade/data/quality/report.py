"""Data quality report generation.

The gap check is honest about not having run: when the bar interval is
unknown and cannot be inferred, ``gap_count`` is ``None`` and
``gap_check_status`` says why. It is never silently zero — "0 gaps" must
mean "measured and found none", not "did not look" (the defect that made
the ETF verdict's gap count meaningless).

Crypto venues trade 24/7/365; exchange-calendar venues legitimately gap
over weekends. When ``always_open`` is not declared it is inferred from the
data (bars on Saturday/Sunday mean an always-open venue), and the value
actually used is reported.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, NamedTuple

import pandas as pd

_INTERVAL_TO_TIMEDELTA = {
    "1m": pd.Timedelta(minutes=1),
    "5m": pd.Timedelta(minutes=5),
    "15m": pd.Timedelta(minutes=15),
    "30m": pd.Timedelta(minutes=30),
    "1h": pd.Timedelta(hours=1),
    "4h": pd.Timedelta(hours=4),
    "1d": pd.Timedelta(days=1),
}
# 24/7 venues (crypto) must not skip bars; exchange-calendar venues legitimately
# gap over weekends/holidays, so only multi-day holes are suspicious there.
_GAP_MULTIPLE_ALWAYS_OPEN = 1.5
_GAP_MULTIPLE_CALENDAR = 3.5
_SPIKE_ROBUST_Z = 10.0
_SPIKE_MIN_ABS_RETURN = 0.15
# Inferring a bar interval from a single spacing would make any two-row frame
# look gap-free by construction; require at least two observed spacings.
_MIN_DIFFS_TO_INFER = 2

GAP_CHECK_MEASURED = "MEASURED"


class _GapCheck(NamedTuple):
    status: str
    gap_count: int | None
    max_gap_multiple: float | None
    interval_label: str


@dataclass
class DataQualityReport:
    row_count: int
    symbol_count: int
    min_timestamp: str
    max_timestamp: str
    missing_values_by_column: dict[str, int]
    duplicate_timestamps_by_symbol: int
    non_monotonic_timestamps: bool
    invalid_ohlc_rows: int
    zero_volume_rows: int
    gap_count: int | None
    max_gap_multiple: float | None
    spike_count: int
    warnings: list[str]
    gap_check_status: str
    expected_interval_used: str
    always_open_used: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _symbol_groups(frame: pd.DataFrame) -> list[tuple[Any, pd.DataFrame]]:
    if "symbol" in frame.columns:
        return [(key, group) for key, group in frame.groupby("symbol")]
    return [(None, frame)]


def _infer_expected_spacing(frame: pd.DataFrame) -> tuple[pd.Timedelta | None, str]:
    """Infer the bar spacing as the median timestamp diff across symbols.

    Returns ``(None, reason)`` when inference is impossible; the caller must
    then report the gap check as not measured, never as zero gaps.
    """
    diffs = [
        group["timestamp"].dropna().sort_values().diff().dropna()
        for _, group in _symbol_groups(frame)
    ]
    combined = pd.concat(diffs) if diffs else pd.Series([], dtype="timedelta64[ns]")
    if len(combined) < _MIN_DIFFS_TO_INFER:
        return None, "not enough rows to infer the bar interval"
    median = combined.median()
    if median <= pd.Timedelta(0):
        return None, "non-positive inferred spacing (duplicate timestamps dominate)"
    return median, f"inferred:{int(median.total_seconds())}s"


def _infer_always_open(frame: pd.DataFrame) -> bool:
    """A venue that prints bars on Saturday or Sunday is an always-open venue."""
    stamps = frame["timestamp"].dropna()
    if stamps.empty:
        return False
    return bool((stamps.dt.weekday >= 5).any())


def _detect_gaps(
    frame: pd.DataFrame, expected_interval: str | None, always_open: bool
) -> _GapCheck:
    """Count bar gaps larger than a tolerance multiple of the expected spacing."""
    if expected_interval is not None:
        expected = _INTERVAL_TO_TIMEDELTA.get(expected_interval)
        if expected is None:
            return _GapCheck(
                f"NOT_MEASURED: unknown expected_interval {expected_interval!r}",
                None,
                None,
                expected_interval,
            )
        interval_label = expected_interval
    else:
        inferred, label = _infer_expected_spacing(frame)
        if inferred is None:
            return _GapCheck(f"NOT_MEASURED: {label}", None, None, "")
        expected = inferred
        interval_label = label
    tolerance = _GAP_MULTIPLE_ALWAYS_OPEN if always_open else _GAP_MULTIPLE_CALENDAR
    gap_count = 0
    max_multiple = 0.0
    for _, group in _symbol_groups(frame):
        diffs = group["timestamp"].sort_values().diff().dropna()
        if diffs.empty:
            continue
        multiples = diffs / expected
        max_multiple = max(max_multiple, float(multiples.max()))
        gap_count += int((multiples > tolerance).sum())
    return _GapCheck(GAP_CHECK_MEASURED, gap_count, max_multiple, interval_label)


def _detect_spikes(frame: pd.DataFrame) -> int:
    """Count close-to-close moves that are extreme outliers vs the symbol's own
    return distribution (robust MAD z-score), the classic fat-finger signature."""
    spikes = 0
    for _, group in _symbol_groups(frame):
        closes = group.sort_values("timestamp")["close"].astype(float)
        returns = closes.pct_change().dropna()
        if len(returns) < 10:
            continue
        median = returns.median()
        mad = (returns - median).abs().median()
        if mad <= 0:
            big = returns.abs() > _SPIKE_MIN_ABS_RETURN
            spikes += int(big.sum())
            continue
        robust_z = (returns - median).abs() / (1.4826 * mad)
        extreme = (robust_z > _SPIKE_ROBUST_Z) & (returns.abs() > _SPIKE_MIN_ABS_RETURN)
        spikes += int(extreme.sum())
    return spikes


def generate_quality_report(
    data: pd.DataFrame,
    expected_interval: str | None = None,
    always_open: bool | None = None,
) -> DataQualityReport:
    frame = data.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    warnings: list[str] = []
    keys = ["symbol", "timestamp"] if "symbol" in frame.columns else ["timestamp"]
    duplicates = int(frame.duplicated(keys).sum())
    invalid = int(
        (
            (frame["high"] < frame[["open", "close", "low"]].max(axis=1))
            | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))
        ).sum()
    )
    zero_volume = int((frame["volume"] == 0).sum())
    non_mono = (
        bool(any(not g["timestamp"].is_monotonic_increasing for _, g in frame.groupby("symbol")))
        if "symbol" in frame.columns
        else not frame["timestamp"].is_monotonic_increasing
    )
    always_open_used = _infer_always_open(frame) if always_open is None else always_open
    gap_check = _detect_gaps(frame, expected_interval, always_open_used)
    spike_count = _detect_spikes(frame)
    if duplicates:
        warnings.append("duplicate timestamp rows detected")
    if invalid:
        warnings.append("invalid OHLC rows detected")
    if zero_volume:
        warnings.append("zero-volume rows detected")
    if gap_check.status != GAP_CHECK_MEASURED:
        warnings.append(
            f"gap check {gap_check.status} — gap_count=None is not zero gaps; "
            "declare expected_interval to measure"
        )
    elif gap_check.gap_count:
        warnings.append(
            f"{gap_check.gap_count} bar gap(s) exceed tolerance "
            f"(max gap = {gap_check.max_gap_multiple:.1f}x expected "
            f"{gap_check.interval_label} spacing)"
        )
    if spike_count:
        warnings.append(
            f"{spike_count} extreme return spike(s) detected (possible bad prints); "
            "inspect before using this dataset for research"
        )
    return DataQualityReport(
        row_count=len(frame),
        symbol_count=int(frame["symbol"].nunique()) if "symbol" in frame.columns else 1,
        min_timestamp=str(frame["timestamp"].min()),
        max_timestamp=str(frame["timestamp"].max()),
        missing_values_by_column={str(k): int(v) for k, v in frame.isna().sum().items()},
        duplicate_timestamps_by_symbol=duplicates,
        non_monotonic_timestamps=non_mono,
        invalid_ohlc_rows=invalid,
        zero_volume_rows=zero_volume,
        gap_count=gap_check.gap_count,
        max_gap_multiple=gap_check.max_gap_multiple,
        spike_count=spike_count,
        warnings=warnings,
        gap_check_status=gap_check.status,
        expected_interval_used=gap_check.interval_label,
        always_open_used=always_open_used,
    )
