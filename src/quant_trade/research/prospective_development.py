"""Offline development falsification for the sealed BTC/ETH campaign.

The evaluator consumes an explicit, caller-owned Binance collection directory.
It performs no discovery, network access, artifact writes, holdout evaluation,
or execution outside the existing bar backtest.  A development result can kill
a hypothesis, but can never promote it: the only verdicts are ``NO_GO`` and
``INSUFFICIENT_EVIDENCE``.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

import numpy as np
import pandas as pd

from quant_trade.backtest.costs import CostModel
from quant_trade.backtest.multi_asset import MultiAssetBacktestResult, run_multi_asset_backtest
from quant_trade.data.panel import validate_panel_schema
from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_bytes, sha256_of_text
from quant_trade.metrics.performance import periods_per_year
from quant_trade.research.prospective_crypto import (
    SYMBOLS,
    ProspectiveStrategySpec,
    development_tsmom_targets,
)

VerdictStatus = Literal["NO_GO", "INSUFFICIENT_EVIDENCE"]

SCHEMA_VERSION = 1
NORMAL_COST_BPS_PER_SIDE = 15.0
STRESS_COST_BPS_PER_SIDE = 30.0
INITIAL_CASH = 100_000.0


class DevelopmentEvidenceError(ValueError):
    """Internal fail-closed evidence error converted to an insufficient verdict."""


@dataclass(frozen=True)
class PerformanceSnapshot:
    """Small, JSON-stable metric set for one development simulation."""

    initial_equity: float
    terminal_equity: float
    total_return: float
    cagr: float
    volatility: float
    sharpe: float
    max_drawdown: float
    trade_count: int
    total_cost: float
    same_bar_fill_count: int
    first_fill_date: str | None
    last_fill_date: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "initial_equity": self.initial_equity,
            "terminal_equity": self.terminal_equity,
            "total_return": self.total_return,
            "cagr": self.cagr,
            "volatility": self.volatility,
            "sharpe": self.sharpe,
            "max_drawdown": self.max_drawdown,
            "trade_count": self.trade_count,
            "total_cost": self.total_cost,
            "same_bar_fill_count": self.same_bar_fill_count,
            "first_fill_date": self.first_fill_date,
            "last_fill_date": self.last_fill_date,
        }


@dataclass(frozen=True)
class ScenarioSnapshot:
    """Strategy and like-for-like benchmarks under one cost scenario."""

    cost_bps_per_side: float
    fill_fraction: float
    strategy: PerformanceSnapshot
    benchmarks: Mapping[str, PerformanceSnapshot]
    block_outperformance_counts: Mapping[str, int]

    def __post_init__(self) -> None:
        object.__setattr__(self, "benchmarks", MappingProxyType(dict(self.benchmarks)))
        object.__setattr__(
            self,
            "block_outperformance_counts",
            MappingProxyType(dict(self.block_outperformance_counts)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "cost_bps_per_side": self.cost_bps_per_side,
            "fill_fraction": self.fill_fraction,
            "strategy": self.strategy.to_dict(),
            "benchmarks": {key: value.to_dict() for key, value in sorted(self.benchmarks.items())},
            "block_outperformance_counts": dict(sorted(self.block_outperformance_counts.items())),
        }


@dataclass(frozen=True)
class DevelopmentVerdict:
    """Reproducible, non-promotional development report."""

    status: VerdictStatus
    strategy_id: str
    decision_start: str
    end_date: str
    evidence_hashes: Mapping[str, str]
    decision_months: int
    signal_count: int
    scenarios: Mapping[str, ScenarioSnapshot]
    reasons: tuple[str, ...]
    schema_version: int = SCHEMA_VERSION
    development_only: bool = True
    promotion_authorized: bool = False
    real_money_authorized: bool = False

    def __post_init__(self) -> None:
        if self.status not in ("NO_GO", "INSUFFICIENT_EVIDENCE"):
            raise ValueError("development verdicts can never be PASS")
        object.__setattr__(self, "evidence_hashes", MappingProxyType(dict(self.evidence_hashes)))
        object.__setattr__(self, "scenarios", MappingProxyType(dict(self.scenarios)))
        object.__setattr__(self, "reasons", tuple(self.reasons))
        if not self.reasons:
            raise ValueError("a development verdict requires at least one reason")
        if self.promotion_authorized or self.real_money_authorized:
            raise ValueError("development evidence cannot authorize promotion or real money")

    def to_dict(self) -> dict[str, Any]:
        """Return a canonical-JSON-compatible report payload."""

        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "strategy_id": self.strategy_id,
            "decision_start": self.decision_start,
            "end_date": self.end_date,
            "evidence_hashes": dict(sorted(self.evidence_hashes.items())),
            "decision_months": self.decision_months,
            "signal_count": self.signal_count,
            "scenarios": {key: value.to_dict() for key, value in sorted(self.scenarios.items())},
            "reasons": list(self.reasons),
            "development_only": self.development_only,
            "promotion_authorized": self.promotion_authorized,
            "real_money_authorized": self.real_money_authorized,
        }

    def report_sha256(self) -> str:
        """Content address of the complete report, excluding no hidden state."""

        return sha256_of_text(canonical_dumps(self.to_dict()))


@dataclass(frozen=True)
class _LoadedEvidence:
    panel: pd.DataFrame
    hashes: Mapping[str, str]


def _parse_iso_date(name: str, value: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise DevelopmentEvidenceError(f"{name.upper()}_IS_NOT_ISO_DATE") from exc


def _read_journal(root: Path) -> tuple[list[dict[str, Any]], bytes]:
    path = root / "journal.jsonl"
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise DevelopmentEvidenceError("JOURNAL_MISSING_OR_UNREADABLE") from exc
    records: list[dict[str, Any]] = []
    try:
        for raw_line in payload.decode("utf-8").splitlines():
            if not raw_line.strip():
                continue
            record = json.loads(raw_line)
            if not isinstance(record, dict):
                raise TypeError("journal row is not an object")
            records.append(record)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise DevelopmentEvidenceError("JOURNAL_IS_NOT_VALID_JSONL") from exc
    if not records:
        raise DevelopmentEvidenceError("JOURNAL_IS_EMPTY")
    return records, payload


def _safe_journal_contract(
    records: list[dict[str, Any]],
    *,
    end_date: date,
) -> dict[str, dict[str, Any]]:
    headers = [record for record in records if record.get("type") == "header"]
    if len(headers) != 1:
        raise DevelopmentEvidenceError("JOURNAL_REQUIRES_EXACTLY_ONE_HEADER")
    header = headers[0]
    policy = header.get("policy")
    if (
        str(header.get("venue", "")).lower() != "binance"
        or not isinstance(policy, dict)
        or str(policy.get("venue", "")).lower() != "binance"
        or str(policy.get("market", "")).lower() != "spot"
        or policy.get("interval") != "1d"
        or policy.get("quote_asset") != "USDT"
    ):
        raise DevelopmentEvidenceError("JOURNAL_IS_NOT_BINANCE_SPOT_USDT_DAILY")
    window = header.get("window")
    if not isinstance(window, list) or len(window) != 2:
        raise DevelopmentEvidenceError("JOURNAL_WINDOW_IS_INVALID")
    journal_end = _parse_iso_date("journal_window_end", str(window[1]))
    if journal_end > end_date:
        # This check intentionally runs before any series file is opened.
        raise DevelopmentEvidenceError("JOURNAL_WINDOW_ENTERS_UNREQUESTED_FUTURE")
    if journal_end < end_date:
        raise DevelopmentEvidenceError("JOURNAL_WINDOW_ENDS_BEFORE_REQUESTED_END")

    symbol_rows = [record for record in records if record.get("type") == "symbol"]
    observed = {str(record.get("symbol", "")).upper() for record in symbol_rows}
    if observed != set(SYMBOLS) or len(symbol_rows) != len(SYMBOLS):
        raise DevelopmentEvidenceError("JOURNAL_SYMBOL_SET_IS_NOT_EXACT")
    indexed: dict[str, dict[str, Any]] = {}
    for record in symbol_rows:
        symbol = str(record.get("symbol", "")).upper()
        if record.get("outcome") != "listed":
            raise DevelopmentEvidenceError(f"{symbol}_IS_NOT_RECORDED_AS_LISTED")
        last_date = _parse_iso_date(f"{symbol}_last_date", str(record.get("last_date", "")))
        if last_date > end_date:
            # Do not hash or parse a file whose trusted envelope says it
            # contains bars outside this development request.
            raise DevelopmentEvidenceError(f"{symbol}_ENTERS_UNREQUESTED_FUTURE")
        if last_date < end_date:
            raise DevelopmentEvidenceError(f"{symbol}_ENDS_BEFORE_REQUESTED_END")
        digest = record.get("series_file_sha256")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise DevelopmentEvidenceError(f"{symbol}_SERIES_DIGEST_IS_INVALID")
        indexed[symbol] = record
    return indexed


def _parse_series(
    root: Path,
    symbol: str,
    record: Mapping[str, Any],
    *,
    end_date: date,
) -> tuple[pd.DataFrame, str]:
    path = root / "series" / f"{symbol}.jsonl"
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise DevelopmentEvidenceError(f"{symbol}_SERIES_MISSING_OR_UNREADABLE") from exc
    digest = sha256_of_bytes(payload)
    if digest != record["series_file_sha256"]:
        raise DevelopmentEvidenceError(f"{symbol}_SERIES_DIGEST_MISMATCH")
    rows: list[dict[str, Any]] = []
    try:
        for raw_line in payload.decode("utf-8").splitlines():
            if not raw_line.strip():
                continue
            raw = json.loads(raw_line)
            if not isinstance(raw, dict):
                raise TypeError("series row is not an object")
            bar_date = _parse_iso_date(f"{symbol}_bar_date", str(raw.get("date", "")))
            if bar_date > end_date:
                raise DevelopmentEvidenceError(f"{symbol}_CONTAINS_UNREQUESTED_FUTURE")
            rows.append(
                {
                    "timestamp": pd.Timestamp(bar_date, tz="UTC"),
                    "symbol": symbol,
                    "open": raw.get("open"),
                    "high": raw.get("high"),
                    "low": raw.get("low"),
                    "close": raw.get("close"),
                    "volume": raw.get("volume_base"),
                }
            )
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise DevelopmentEvidenceError(f"{symbol}_SERIES_IS_NOT_VALID_JSONL") from exc
    if len(rows) != int(record.get("row_count", -1)):
        raise DevelopmentEvidenceError(f"{symbol}_ROW_COUNT_MISMATCH")
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise DevelopmentEvidenceError(f"{symbol}_SERIES_IS_EMPTY")
    first = frame["timestamp"].iloc[0].date()
    last = frame["timestamp"].iloc[-1].date()
    recorded_first = _parse_iso_date(f"{symbol}_first_date", str(record.get("first_date", "")))
    recorded_last = _parse_iso_date(f"{symbol}_last_date", str(record.get("last_date", "")))
    if first != recorded_first or last != recorded_last:
        raise DevelopmentEvidenceError(f"{symbol}_SERIES_BOUNDS_MISMATCH")
    return frame, digest


def _load_evidence(root: Path, *, end_date: date) -> _LoadedEvidence:
    records, journal_bytes = _read_journal(root)
    symbol_records = _safe_journal_contract(records, end_date=end_date)
    frames: list[pd.DataFrame] = []
    hashes = {"journal.jsonl": sha256_of_bytes(journal_bytes)}
    for symbol in SYMBOLS:
        frame, digest = _parse_series(
            root,
            symbol,
            symbol_records[symbol],
            end_date=end_date,
        )
        frames.append(frame)
        hashes[f"series/{symbol}.jsonl"] = digest
    try:
        panel = validate_panel_schema(pd.concat(frames, ignore_index=True))
    except ValueError as exc:
        raise DevelopmentEvidenceError("SERIES_FAILS_CANONICAL_OHLCV_VALIDATION") from exc

    timestamp_sets = {
        symbol: tuple(panel.loc[panel["symbol"] == symbol, "timestamp"]) for symbol in SYMBOLS
    }
    if timestamp_sets[SYMBOLS[0]] != timestamp_sets[SYMBOLS[1]]:
        raise DevelopmentEvidenceError("SYMBOL_CALENDARS_ARE_NOT_IDENTICAL")
    calendar = pd.DatetimeIndex(timestamp_sets[SYMBOLS[0]])
    expected = pd.date_range(calendar[0], calendar[-1], freq="D", tz="UTC")
    if not calendar.equals(expected):
        raise DevelopmentEvidenceError("DAILY_CALENDAR_HAS_GAPS_OR_DUPLICATES")
    hashes["dataset"] = sha256_of_text(canonical_dumps(dict(sorted(hashes.items()))))
    return _LoadedEvidence(panel=panel, hashes=hashes)


def _cost_model(cost_bps_per_side: float) -> CostModel:
    # Preserve the campaign's declared 10 bps fee + 5 bps friction split.
    multiplier = cost_bps_per_side / NORMAL_COST_BPS_PER_SIDE
    return CostModel(
        percentage_commission=0.001 * multiplier,
        spread_bps=5.0 * multiplier,
    )


def _run_single_sleeve(
    panel: pd.DataFrame,
    symbol: str,
    targets: pd.DataFrame,
    *,
    initial_cash: float,
    cost_model: CostModel,
) -> MultiAssetBacktestResult:
    symbol_panel = panel[panel["symbol"] == symbol].reset_index(drop=True)
    return run_multi_asset_backtest(
        symbol_panel,
        targets,
        initial_cash=initial_cash,
        cost_model=cost_model,
        max_weight_per_asset=1.0,
        allow_leverage=False,
        allow_short=False,
        fractional_shares=True,
        rebalance_band=0.0,
        max_gross_exposure=1.0,
    )


def _combine_results(
    results: list[MultiAssetBacktestResult],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    equity_parts = [
        result.equity_curve.set_index("timestamp")["equity"].rename(str(index))
        for index, result in enumerate(results)
    ]
    combined = pd.concat(equity_parts, axis=1, join="inner")
    equity = combined.sum(axis=1).rename("equity").reset_index()
    trades = pd.concat([result.trades for result in results], ignore_index=True)
    return equity, trades


def _snapshot(
    equity_curve: pd.DataFrame,
    trades: pd.DataFrame,
    *,
    decision_timestamps: set[pd.Timestamp],
) -> PerformanceSnapshot:
    equity = equity_curve["equity"].astype(float)
    returns = equity.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    ppy = periods_per_year(equity_curve["timestamp"])
    years = max(len(equity) / ppy, 1 / ppy)
    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1.0)
    cagr = float((equity.iloc[-1] / equity.iloc[0]) ** (1.0 / years) - 1.0)
    volatility = float(returns.std(ddof=0) * math.sqrt(ppy)) if len(returns) > 1 else 0.0
    sharpe = float(returns.mean() * ppy / volatility) if volatility > 0 else 0.0
    drawdown = equity / equity.cummax() - 1.0
    if trades.empty:
        fill_dates = pd.Series(dtype="datetime64[ns, UTC]")
        total_cost = 0.0
    else:
        fill_dates = pd.to_datetime(trades["timestamp"], utc=True)
        total_cost = float(pd.to_numeric(trades["cost"], errors="raise").sum())
    same_bar = int(fill_dates.isin(decision_timestamps).sum())
    return PerformanceSnapshot(
        initial_equity=float(equity.iloc[0]),
        terminal_equity=float(equity.iloc[-1]),
        total_return=total_return,
        cagr=cagr,
        volatility=volatility,
        sharpe=sharpe,
        max_drawdown=float(drawdown.min()),
        trade_count=len(trades),
        total_cost=total_cost,
        same_bar_fill_count=same_bar,
        first_fill_date=(fill_dates.min().date().isoformat() if len(fill_dates) else None),
        last_fill_date=(fill_dates.max().date().isoformat() if len(fill_dates) else None),
    )


def _strategy_result(
    panel: pd.DataFrame,
    sparse_targets: pd.DataFrame,
    spec: ProspectiveStrategySpec,
    *,
    initial_cash: float,
    cost_model: CostModel,
    fill_fraction: float,
) -> tuple[pd.DataFrame, pd.DataFrame, set[pd.Timestamp]]:
    results: list[MultiAssetBacktestResult] = []
    decisions: set[pd.Timestamp] = set()
    for symbol in spec.symbols:
        sleeve = float(spec.sleeves[symbol])
        symbol_targets = sparse_targets[sparse_targets["symbol"] == symbol].copy()
        decisions.update(pd.to_datetime(symbol_targets["decision_timestamp"], utc=True))
        engine_targets = symbol_targets.rename(columns={"decision_timestamp": "timestamp"})[
            ["timestamp", "symbol", "target_weight"]
        ]
        normalized = engine_targets["target_weight"] / sleeve
        # The sealed stress proxy deterministically executes only the declared
        # fraction of desired LONG exposure. CASH exits remain complete so the
        # proxy cannot improve results by trapping a losing position.
        engine_targets["target_weight"] = np.where(
            normalized > 0.0, normalized * fill_fraction, normalized
        )
        results.append(
            _run_single_sleeve(
                panel,
                str(symbol),
                engine_targets,
                initial_cash=initial_cash * sleeve,
                cost_model=cost_model,
            )
        )
    equity, trades = _combine_results(results)
    return equity, trades, decisions


def _buy_and_hold_result(
    panel: pd.DataFrame,
    symbol_allocations: Mapping[str, float],
    *,
    decision_timestamp: pd.Timestamp,
    initial_cash: float,
    cost_model: CostModel,
    fill_fraction: float,
) -> tuple[pd.DataFrame, pd.DataFrame, set[pd.Timestamp]]:
    results: list[MultiAssetBacktestResult] = []
    for symbol, allocation in symbol_allocations.items():
        target = pd.DataFrame(
            [
                {
                    "timestamp": decision_timestamp,
                    "symbol": symbol,
                    "target_weight": fill_fraction,
                }
            ]
        )
        results.append(
            _run_single_sleeve(
                panel,
                symbol,
                target,
                initial_cash=initial_cash * allocation,
                cost_model=cost_model,
            )
        )
    equity, trades = _combine_results(results)
    return equity, trades, {decision_timestamp}


def _scenario(
    panel: pd.DataFrame,
    sparse_targets: pd.DataFrame,
    spec: ProspectiveStrategySpec,
    *,
    decision_start: pd.Timestamp,
    cost_bps_per_side: float,
    fill_fraction: float,
    block_count: int,
    block_partition_method: str,
    block_benchmark_ids: tuple[str, ...],
) -> ScenarioSnapshot:
    cost = _cost_model(cost_bps_per_side)
    strategy_equity, strategy_trades, strategy_decisions = _strategy_result(
        panel,
        sparse_targets,
        spec,
        initial_cash=INITIAL_CASH,
        cost_model=cost,
        fill_fraction=fill_fraction,
    )
    strategy = _snapshot(
        strategy_equity,
        strategy_trades,
        decision_timestamps=strategy_decisions,
    )
    allocations = {
        str(benchmark["benchmark_id"]): {
            str(symbol): float(weight) for symbol, weight in benchmark["symbol_weights"].items()
        }
        for benchmark in spec.benchmarks
    }
    benchmarks: dict[str, PerformanceSnapshot] = {}
    benchmark_equities: dict[str, pd.DataFrame] = {}
    for benchmark_id, allocation in allocations.items():
        equity, trades, decisions = _buy_and_hold_result(
            panel,
            allocation,
            decision_timestamp=decision_start,
            initial_cash=INITIAL_CASH,
            cost_model=cost,
            fill_fraction=fill_fraction,
        )
        benchmark_equities[benchmark_id] = equity
        benchmarks[benchmark_id] = _snapshot(
            equity,
            trades,
            decision_timestamps=decisions,
        )
    outperformance = _block_outperformance(
        strategy_equity,
        benchmark_equities,
        block_count=block_count,
        block_partition_method=block_partition_method,
        benchmark_ids=block_benchmark_ids,
    )
    return ScenarioSnapshot(
        cost_bps_per_side=cost_bps_per_side,
        fill_fraction=fill_fraction,
        strategy=strategy,
        benchmarks=benchmarks,
        block_outperformance_counts=outperformance,
    )


def _block_outperformance(
    strategy_equity: pd.DataFrame,
    benchmark_equities: Mapping[str, pd.DataFrame],
    *,
    block_count: int,
    block_partition_method: str,
    benchmark_ids: tuple[str, ...],
) -> dict[str, int]:
    """Count strictly superior strategy returns in equal contiguous blocks."""

    if block_partition_method != "EQUAL_CONTIGUOUS_DAILY_OBSERVATIONS":
        raise DevelopmentEvidenceError("UNSUPPORTED_BLOCK_PARTITION_METHOD")
    if block_count < 1 or len(strategy_equity) < block_count:
        raise DevelopmentEvidenceError("NOT_ENOUGH_BARS_FOR_CONTIGUOUS_BLOCKS")
    aligned = strategy_equity.set_index("timestamp")[["equity"]].rename(
        columns={"equity": "strategy"}
    )
    for benchmark_id in benchmark_ids:
        if benchmark_id not in benchmark_equities:
            raise DevelopmentEvidenceError(f"MISSING_BLOCK_BENCHMARK:{benchmark_id}")
        aligned = aligned.join(
            benchmark_equities[benchmark_id]
            .set_index("timestamp")[["equity"]]
            .rename(columns={"equity": benchmark_id}),
            how="inner",
        )
    if len(aligned) < block_count or aligned.isna().any().any():
        raise DevelopmentEvidenceError("BLOCK_EQUITY_CURVES_DO_NOT_ALIGN")
    counts = {benchmark_id: 0 for benchmark_id in benchmark_ids}
    for positions in np.array_split(np.arange(len(aligned)), block_count):
        if len(positions) == 0:
            raise DevelopmentEvidenceError("EMPTY_CONTIGUOUS_BLOCK")
        block = aligned.iloc[positions]
        strategy_return = float(block["strategy"].iloc[-1] / block["strategy"].iloc[0] - 1.0)
        for benchmark_id in benchmark_ids:
            benchmark_return = float(
                block[benchmark_id].iloc[-1] / block[benchmark_id].iloc[0] - 1.0
            )
            counts[benchmark_id] += int(strategy_return > benchmark_return)
    return counts


def _insufficient(
    spec: ProspectiveStrategySpec,
    *,
    decision_start: str,
    end_date: str,
    hashes: Mapping[str, str],
    reason: str,
) -> DevelopmentVerdict:
    return DevelopmentVerdict(
        status="INSUFFICIENT_EVIDENCE",
        strategy_id=spec.strategy_id,
        decision_start=decision_start,
        end_date=end_date,
        evidence_hashes=hashes,
        decision_months=0,
        signal_count=0,
        scenarios={},
        reasons=(reason, "DEVELOPMENT_ONLY_CANNOT_AUTHORIZE_PROMOTION"),
    )


def evaluate_prospective_development(
    data_directory: str | Path,
    spec: ProspectiveStrategySpec,
    *,
    decision_start: str,
    end_date: str,
) -> DevelopmentVerdict:
    """Falsify the frozen campaign using an explicit offline development slice.

    The collection journal must declare an exact end at ``end_date``.  If its
    envelope says any series extends later, the evaluator returns before
    opening a series file.  This avoids the unsafe read-then-filter behavior
    that could expose prospective or other unrequested data.
    """

    hashes: dict[str, str] = {}
    try:
        validated_spec = ProspectiveStrategySpec(**spec.canonical_payload())
        if validated_spec.seal() != spec.seal():
            raise DevelopmentEvidenceError("SPEC_RECONSTRUCTION_MISMATCH")
        hashes["spec"] = spec.seal()
        start = _parse_iso_date("decision_start", decision_start)
        end = _parse_iso_date("end_date", end_date)
        evidence_start = _parse_iso_date(
            "development_evidence_start",
            str(getattr(spec, "development_evidence_start", "")),
        )
        evidence_end = _parse_iso_date(
            "development_evidence_end",
            str(getattr(spec, "development_evidence_end", "")),
        )
        if end < start:
            raise DevelopmentEvidenceError("END_PRECEDES_DECISION_START")
        if start < evidence_start:
            raise DevelopmentEvidenceError("START_PRECEDES_SEALED_DEVELOPMENT_EVIDENCE")
        if end > evidence_end:
            raise DevelopmentEvidenceError("END_EXCEEDS_SEALED_DEVELOPMENT_EVIDENCE")
        loaded = _load_evidence(Path(data_directory), end_date=end)
        hashes.update(loaded.hashes)
    except (AttributeError, DevelopmentEvidenceError, TypeError, ValueError) as exc:
        reason = str(exc) or type(exc).__name__.upper()
        return _insufficient(
            spec,
            decision_start=decision_start,
            end_date=end_date,
            hashes=hashes,
            reason=reason,
        )

    start_timestamp = pd.Timestamp(start, tz="UTC")
    end_timestamp = pd.Timestamp(end, tz="UTC")
    panel = loaded.panel
    if start_timestamp not in set(panel["timestamp"]):
        return _insufficient(
            spec,
            decision_start=decision_start,
            end_date=end_date,
            hashes=hashes,
            reason="DECISION_START_IS_NOT_A_DAILY_BAR",
        )
    evaluation_panel = panel[
        panel["timestamp"].between(start_timestamp, end_timestamp, inclusive="both")
    ].reset_index(drop=True)
    complete_month_ends = evaluation_panel[evaluation_panel["timestamp"].dt.is_month_end]
    decision_months = int(
        (complete_month_ends.groupby("timestamp")["symbol"].nunique() == len(SYMBOLS)).sum()
    )
    try:
        sparse_targets = development_tsmom_targets(
            panel,
            spec,
            decision_start=decision_start,
            decision_end=end_date,
        )
    except ValueError as exc:
        return _insufficient(
            spec,
            decision_start=decision_start,
            end_date=end_date,
            hashes=hashes,
            reason=f"SIGNAL_CONTRACT_REJECTED_EVIDENCE:{exc}",
        )
    target_symbols = set(sparse_targets["symbol"])
    if sparse_targets.empty or target_symbols != set(SYMBOLS):
        return DevelopmentVerdict(
            status="INSUFFICIENT_EVIDENCE",
            strategy_id=spec.strategy_id,
            decision_start=decision_start,
            end_date=end_date,
            evidence_hashes=hashes,
            decision_months=decision_months,
            signal_count=len(sparse_targets),
            scenarios={},
            reasons=(
                "BOTH_SLEEVES_REQUIRE_AN_INITIAL_STATE",
                "DEVELOPMENT_ONLY_CANNOT_AUTHORIZE_PROMOTION",
            ),
        )

    policy = spec.development_falsification_policy
    normal_cost_bps = float(spec.cost_policy["fee_floor_bps_per_side"]) + float(
        spec.cost_policy["friction_floor_bps_per_side"]
    )
    stress_multiplier = float(policy["stress_cost_multiplier"])
    stress_fill_fraction = float(policy["stress_fill_fraction"])
    block_count = int(policy["contiguous_blocks"])
    block_partition_method = str(policy["block_partition_method"])
    minimum_outperforming_blocks = int(policy["minimum_outperforming_blocks"])
    required_benchmark_ids = tuple(str(value) for value in policy["required_benchmark_ids"])
    block_benchmark_ids = tuple(
        str(value) for value in policy["block_outperformance_benchmark_ids"]
    )
    try:
        scenarios = {
            "normal": _scenario(
                evaluation_panel,
                sparse_targets,
                spec,
                decision_start=start_timestamp,
                cost_bps_per_side=normal_cost_bps,
                fill_fraction=1.0,
                block_count=block_count,
                block_partition_method=block_partition_method,
                block_benchmark_ids=block_benchmark_ids,
            ),
            "stress_2x_fills_50pct": _scenario(
                evaluation_panel,
                sparse_targets,
                spec,
                decision_start=start_timestamp,
                cost_bps_per_side=normal_cost_bps * stress_multiplier,
                fill_fraction=stress_fill_fraction,
                block_count=block_count,
                block_partition_method=block_partition_method,
                block_benchmark_ids=block_benchmark_ids,
            ),
        }
    except (DevelopmentEvidenceError, ValueError) as exc:
        return DevelopmentVerdict(
            status="INSUFFICIENT_EVIDENCE",
            strategy_id=spec.strategy_id,
            decision_start=decision_start,
            end_date=end_date,
            evidence_hashes=hashes,
            decision_months=decision_months,
            signal_count=len(sparse_targets),
            scenarios={},
            reasons=(str(exc), "DEVELOPMENT_ONLY_CANNOT_AUTHORIZE_PROMOTION"),
        )
    reasons: list[str] = []
    normal = scenarios["normal"]
    stress = scenarios["stress_2x_fills_50pct"]
    if bool(policy["net_total_return_positive"]) and normal.strategy.total_return <= 0.0:
        reasons.append("NORMAL_NET_TOTAL_RETURN_IS_NOT_POSITIVE")
    for benchmark_id in required_benchmark_ids:
        if (
            bool(policy["outperform_each_benchmark"])
            and normal.strategy.total_return <= normal.benchmarks[benchmark_id].total_return
        ):
            reasons.append(f"NORMAL_RETURN_DOES_NOT_EXCEED_{benchmark_id.upper()}")
    for benchmark_id in block_benchmark_ids:
        observed_blocks = normal.block_outperformance_counts[benchmark_id]
        if observed_blocks < minimum_outperforming_blocks:
            reasons.append(
                f"OUTPERFORMS_{benchmark_id.upper()}_IN_{observed_blocks}_OF_{block_count}_BLOCKS"
            )
    max_drawdown_abs = float(policy["max_drawdown_abs"])
    if normal.strategy.max_drawdown < -max_drawdown_abs:
        reasons.append(f"NORMAL_MAX_DRAWDOWN_EXCEEDS_{max_drawdown_abs:.6f}_ABS")
    if stress.strategy.total_return < float(policy["stress_total_return_min"]):
        reasons.append("STRESS_2X_RETURN_IS_NEGATIVE")
    if normal.strategy.same_bar_fill_count or stress.strategy.same_bar_fill_count:
        reasons.append("SAME_BAR_FILL_DETECTED")

    if reasons:
        status: VerdictStatus = "NO_GO"
    else:
        status = "INSUFFICIENT_EVIDENCE"
        reasons.append("DEVELOPMENT_RULE_NOT_FALSIFIED_BUT_PROSPECTIVE_EVIDENCE_IS_REQUIRED")
    reasons.append("DEVELOPMENT_ONLY_CANNOT_AUTHORIZE_PROMOTION")
    return DevelopmentVerdict(
        status=status,
        strategy_id=spec.strategy_id,
        decision_start=decision_start,
        end_date=end_date,
        evidence_hashes=hashes,
        decision_months=decision_months,
        signal_count=len(sparse_targets),
        scenarios=scenarios,
        reasons=tuple(reasons),
    )


__all__ = [
    "DevelopmentVerdict",
    "NORMAL_COST_BPS_PER_SIDE",
    "PerformanceSnapshot",
    "STRESS_COST_BPS_PER_SIDE",
    "ScenarioSnapshot",
    "evaluate_prospective_development",
]
