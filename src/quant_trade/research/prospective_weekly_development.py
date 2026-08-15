"""Fail-closed offline development test for sealed BTC weekly momentum.

This module has no network client and cannot promote a strategy.  It accepts
one explicit Binance collection whose trusted journal envelope is inspected
before the BTC series is opened.  Any missing, mixed, old-policy, post-cutoff,
or non-gapless evidence becomes ``INSUFFICIENT_EVIDENCE``.
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
from quant_trade.data.universe import UniverseCollectorError, verify_journal_chain
from quant_trade.data.venue_klines import (
    VENUE_POLICIES,
    VENUE_POLICY_SHA256,
    HttpResponse,
    parse_kline_page,
)
from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_bytes, sha256_of_text
from quant_trade.evidence.receipts import (
    load_receipts,
    normalized_rows_sha256,
    verify_receipt_chain,
)
from quant_trade.metrics.performance import periods_per_year
from quant_trade.research.prospective_weekly_momentum import (
    DEVELOPMENT_DATA_START,
    DEVELOPMENT_DECISION_END,
    DEVELOPMENT_DECISION_START,
    DEVELOPMENT_EVIDENCE_END,
    STRATEGY_ID,
    SYMBOL,
    WeeklyMomentumSpec,
    development_weekly_momentum_targets,
)

VerdictStatus = Literal["NO_GO", "INSUFFICIENT_EVIDENCE"]
SCHEMA_VERSION = 1
INITIAL_CASH = 100_000.0
NORMAL_COST_BPS_PER_SIDE = 15.0
STRESS_COST_BPS_PER_SIDE = 30.0
EXPECTED_END = date.fromisoformat(DEVELOPMENT_EVIDENCE_END)
EXPECTED_END_MS = 1_701_129_600_000


class WeeklyDevelopmentEvidenceError(ValueError):
    """Evidence violation converted into a non-promotional verdict."""


@dataclass(frozen=True)
class WeeklyPerformanceSnapshot:
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
class WeeklyScenarioSnapshot:
    cost_bps_per_side: float
    long_fill_fraction: float
    strategy: WeeklyPerformanceSnapshot
    benchmarks: Mapping[str, WeeklyPerformanceSnapshot]
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
            "long_fill_fraction": self.long_fill_fraction,
            "strategy": self.strategy.to_dict(),
            "benchmarks": {key: value.to_dict() for key, value in sorted(self.benchmarks.items())},
            "block_outperformance_counts": dict(sorted(self.block_outperformance_counts.items())),
        }


@dataclass(frozen=True)
class WeeklyDevelopmentVerdict:
    status: VerdictStatus
    strategy_id: str
    decision_start: str
    decision_end: str
    evidence_end: str
    evidence_hashes: Mapping[str, str]
    completed_decisions: int
    signal_count: int
    scenarios: Mapping[str, WeeklyScenarioSnapshot]
    reasons: tuple[str, ...]
    schema_version: int = SCHEMA_VERSION
    development_only: bool = True
    promotion_authorized: bool = False
    live_execution_authorized: bool = False
    real_money_authorized: bool = False

    def __post_init__(self) -> None:
        if self.status not in ("NO_GO", "INSUFFICIENT_EVIDENCE"):
            raise ValueError("weekly development verdicts can never be PASS")
        if not self.reasons:
            raise ValueError("weekly development verdict requires a reason")
        if (
            self.promotion_authorized
            or self.live_execution_authorized
            or self.real_money_authorized
        ):
            raise ValueError("weekly development evidence cannot authorize promotion or money")
        object.__setattr__(self, "evidence_hashes", MappingProxyType(dict(self.evidence_hashes)))
        object.__setattr__(self, "scenarios", MappingProxyType(dict(self.scenarios)))
        object.__setattr__(self, "reasons", tuple(self.reasons))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "strategy_id": self.strategy_id,
            "decision_start": self.decision_start,
            "decision_end": self.decision_end,
            "evidence_end": self.evidence_end,
            "evidence_hashes": dict(sorted(self.evidence_hashes.items())),
            "completed_decisions": self.completed_decisions,
            "signal_count": self.signal_count,
            "scenarios": {key: value.to_dict() for key, value in sorted(self.scenarios.items())},
            "reasons": list(self.reasons),
            "development_only": self.development_only,
            "promotion_authorized": self.promotion_authorized,
            "live_execution_authorized": self.live_execution_authorized,
            "real_money_authorized": self.real_money_authorized,
        }

    def report_sha256(self) -> str:
        return sha256_of_text(canonical_dumps(self.to_dict()))


def _iso(name: str, value: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise WeeklyDevelopmentEvidenceError(f"{name.upper()}_IS_NOT_ISO_DATE") from exc


def _read_journal(root: Path) -> tuple[list[dict[str, Any]], bytes]:
    try:
        payload = (root / "journal.jsonl").read_bytes()
        records = [
            json.loads(line) for line in payload.decode("utf-8").splitlines() if line.strip()
        ]
        if not records or any(not isinstance(record, dict) for record in records):
            raise ValueError("empty or non-object journal")
        verify_journal_chain(records)
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        UniverseCollectorError,
    ) as exc:
        raise WeeklyDevelopmentEvidenceError("JOURNAL_ENVELOPE_INVALID") from exc
    return records, payload


def _journal_symbol_record(records: list[dict[str, Any]]) -> dict[str, Any]:
    # Deliberately inspect the complete trusted envelope before opening series bytes.
    headers = [record for record in records if record.get("type") == "header"]
    if len(headers) != 1 or records[0] is not headers[0]:
        raise WeeklyDevelopmentEvidenceError("JOURNAL_REQUIRES_EXACTLY_ONE_GENESIS_HEADER")
    header = headers[0]
    expected_policy = VENUE_POLICIES["binance"]
    policy = header.get("policy")
    if (
        header.get("venue") != "binance"
        or header.get("policy_sha256") != VENUE_POLICY_SHA256["binance"]
        or not isinstance(policy, dict)
        or canonical_dumps(policy) != canonical_dumps(expected_policy)
    ):
        raise WeeklyDevelopmentEvidenceError("JOURNAL_REQUEST_POLICY_IS_NOT_CURRENT_BINANCE")
    template = str(policy.get("url_template", ""))
    if "endTime={end_ms}" not in template:
        raise WeeklyDevelopmentEvidenceError("BINANCE_REQUEST_POLICY_LACKS_HARD_ENDTIME")
    if (
        str(policy.get("market", "")).lower() != "spot"
        or policy.get("interval") != "1d"
        or policy.get("quote_asset") != "USDT"
    ):
        raise WeeklyDevelopmentEvidenceError("JOURNAL_IS_NOT_BINANCE_SPOT_USDT_DAILY")
    window = header.get("window")
    if window != [DEVELOPMENT_DATA_START, DEVELOPMENT_EVIDENCE_END]:
        raise WeeklyDevelopmentEvidenceError("JOURNAL_WINDOW_MUST_END_AT_EXACT_CUTOFF")
    if header.get("clock_source") != "system" or header.get("provenance") == "test_only":
        raise WeeklyDevelopmentEvidenceError("JOURNAL_IS_NOT_FRESH_REAL_COLLECTION")
    rows = [record for record in records if record.get("type") == "symbol"]
    if len(rows) != 1 or str(rows[0].get("symbol", "")).upper() != SYMBOL:
        raise WeeklyDevelopmentEvidenceError("JOURNAL_SYMBOL_SET_IS_NOT_BTC_ONLY")
    record = rows[0]
    if record.get("outcome") != "listed":
        raise WeeklyDevelopmentEvidenceError("BTCUSDT_IS_NOT_RECORDED_AS_LISTED")
    if _iso("series_last", str(record.get("last_date", ""))) != EXPECTED_END:
        raise WeeklyDevelopmentEvidenceError("BTCUSDT_SERIES_DOES_NOT_END_AT_CUTOFF")
    digest = record.get("series_file_sha256")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(c not in "0123456789abcdef" for c in digest)
    ):
        raise WeeklyDevelopmentEvidenceError("BTCUSDT_SERIES_DIGEST_IS_INVALID")
    return record


def _verify_receipts(root: Path, record: Mapping[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    """Verify the complete request/raw/normalization chain before series parse."""

    path = root / "receipts.jsonl"
    try:
        receipt_bytes = path.read_bytes()
        receipts = load_receipts(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise WeeklyDevelopmentEvidenceError("RECEIPTS_MISSING_OR_INVALID") from exc
    if not receipts:
        raise WeeklyDevelopmentEvidenceError("RECEIPTS_MISSING_OR_INVALID")
    if verify_receipt_chain(receipts):
        raise WeeklyDevelopmentEvidenceError("RECEIPT_CHAIN_INVALID")
    root_resolved = root.resolve()
    observed_shas: list[str] = []
    rebuilt_by_start: dict[int, dict[str, Any]] = {}
    for receipt in receipts:
        params = receipt.get("request_parameters")
        if (
            receipt.get("provider_or_venue") != "binance"
            or receipt.get("adapter_name") != "data.venue_klines.binance_spot"
            or receipt.get("source_kind") != "live"
            or not isinstance(params, dict)
            or str(params.get("symbol", "")).upper() != SYMBOL
            or params.get("end_ms") != EXPECTED_END_MS
            or not isinstance(params.get("start_ms"), int)
            or not 0 <= int(params["start_ms"]) <= EXPECTED_END_MS
        ):
            raise WeeklyDevelopmentEvidenceError("RECEIPT_REQUEST_IS_NOT_CAUSAL_LIVE_BINANCE_BTC")
        raw_sha = str(receipt.get("raw_sha256", ""))
        raw_path = Path(str(receipt.get("raw_path", "")))
        if raw_path.is_absolute():
            raise WeeklyDevelopmentEvidenceError("RECEIPT_RAW_PATH_ESCAPES_COLLECTION")
        candidate = (root_resolved / raw_path).resolve()
        try:
            candidate.relative_to(root_resolved)
            raw = candidate.read_bytes()
        except (ValueError, OSError) as exc:
            raise WeeklyDevelopmentEvidenceError("RECEIPT_RAW_BYTES_MISSING_OR_ESCAPING") from exc
        if sha256_of_bytes(raw) != raw_sha:
            raise WeeklyDevelopmentEvidenceError("RECEIPT_RAW_SHA256_MISMATCH")
        try:
            normalized = parse_kline_page(
                HttpResponse(status=int(receipt.get("http_status", 0)), body=raw),
                symbol=SYMBOL,
                venue="binance",
            )
        except (TypeError, ValueError) as exc:
            raise WeeklyDevelopmentEvidenceError("RECEIPT_RAW_PAGE_CANNOT_BE_REPARSED") from exc
        if normalized_rows_sha256(normalized) != receipt.get("normalized_rows_sha256"):
            raise WeeklyDevelopmentEvidenceError("RECEIPT_NORMALIZED_ROWS_SHA256_MISMATCH")
        for row in normalized:
            start_ms = int(row["start_ms"])
            if start_ms > EXPECTED_END_MS:
                raise WeeklyDevelopmentEvidenceError("RECEIPT_RAW_PAGE_CONTAINS_POST_CUTOFF_BAR")
            previous = rebuilt_by_start.get(start_ms)
            if previous is not None and canonical_dumps(previous) != canonical_dumps(row):
                raise WeeklyDevelopmentEvidenceError("RECEIPT_PAGES_CONTRADICT_ON_DUPLICATE_BAR")
            rebuilt_by_start[start_ms] = row
        observed_shas.append(raw_sha)
    if observed_shas != list(record.get("raw_sha256s", [])):
        raise WeeklyDevelopmentEvidenceError("RECEIPT_RAW_SHA_SEQUENCE_DOES_NOT_MATCH_JOURNAL")
    rebuilt = [rebuilt_by_start[key] for key in sorted(rebuilt_by_start)]
    if not rebuilt:
        raise WeeklyDevelopmentEvidenceError("RECEIPT_PAGES_REBUILD_EMPTY_SERIES")
    return sha256_of_bytes(receipt_bytes), rebuilt


def _parse_series(
    root: Path,
    record: Mapping[str, Any],
    rebuilt_rows: list[dict[str, Any]],
) -> tuple[pd.DataFrame, str]:
    try:
        payload = (root / "series" / f"{SYMBOL}.jsonl").read_bytes()
    except OSError as exc:
        raise WeeklyDevelopmentEvidenceError("BTCUSDT_SERIES_MISSING_OR_UNREADABLE") from exc
    digest = sha256_of_bytes(payload)
    if digest != record["series_file_sha256"]:
        raise WeeklyDevelopmentEvidenceError("BTCUSDT_SERIES_DIGEST_MISMATCH")
    expected_payload = ("".join(canonical_dumps(row) + "\n" for row in rebuilt_rows)).encode(
        "utf-8"
    )
    if payload != expected_payload:
        raise WeeklyDevelopmentEvidenceError("BTCUSDT_SERIES_DOES_NOT_EQUAL_RECEIPT_REBUILD")
    rows: list[dict[str, Any]] = []
    try:
        for line in payload.decode("utf-8").splitlines():
            if not line.strip():
                continue
            raw = json.loads(line)
            if not isinstance(raw, dict):
                raise TypeError("series row is not an object")
            bar_date = _iso("bar_date", str(raw.get("date", "")))
            if bar_date > EXPECTED_END:
                raise WeeklyDevelopmentEvidenceError("BTCUSDT_CONTAINS_POST_CUTOFF_BAR")
            rows.append(
                {
                    "timestamp": pd.Timestamp(bar_date, tz="UTC"),
                    "symbol": SYMBOL,
                    "open": raw.get("open"),
                    "high": raw.get("high"),
                    "low": raw.get("low"),
                    "close": raw.get("close"),
                    "volume": raw.get("volume_base"),
                }
            )
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise WeeklyDevelopmentEvidenceError("BTCUSDT_SERIES_IS_NOT_VALID_JSONL") from exc
    if len(rows) != int(record.get("row_count", -1)) or not rows:
        raise WeeklyDevelopmentEvidenceError("BTCUSDT_ROW_COUNT_MISMATCH_OR_EMPTY")
    try:
        panel = validate_panel_schema(pd.DataFrame(rows))
    except ValueError as exc:
        raise WeeklyDevelopmentEvidenceError("BTCUSDT_FAILS_CANONICAL_OHLCV_VALIDATION") from exc
    calendar = pd.DatetimeIndex(panel["timestamp"])
    expected = pd.date_range(calendar[0], pd.Timestamp(EXPECTED_END, tz="UTC"), freq="D")
    if not calendar.equals(expected):
        raise WeeklyDevelopmentEvidenceError("BTCUSDT_DAILY_UTC_CALENDAR_HAS_GAPS_OR_DUPLICATES")
    if calendar[0].date() != date.fromisoformat(DEVELOPMENT_DATA_START) or calendar[
        0
    ].date() != _iso("record_first", str(record.get("first_date", ""))):
        raise WeeklyDevelopmentEvidenceError("BTCUSDT_SERIES_BOUNDS_MISMATCH")
    return panel, digest


def _cost_model(bps: float) -> CostModel:
    multiplier = bps / NORMAL_COST_BPS_PER_SIDE
    return CostModel(percentage_commission=0.001 * multiplier, spread_bps=5.0 * multiplier)


def _snapshot(
    result: MultiAssetBacktestResult, decisions: set[pd.Timestamp]
) -> WeeklyPerformanceSnapshot:
    curve = result.equity_curve
    equity = curve["equity"].astype(float)
    returns = equity.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    ppy = periods_per_year(curve["timestamp"])
    years = max(len(equity) / ppy, 1.0 / ppy)
    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1.0)
    volatility = float(returns.std(ddof=0) * math.sqrt(ppy)) if len(returns) > 1 else 0.0
    trades = result.trades
    fill_dates = (
        pd.to_datetime(trades["timestamp"], utc=True)
        if not trades.empty
        else pd.Series(dtype="datetime64[ns, UTC]")
    )
    return WeeklyPerformanceSnapshot(
        initial_equity=float(equity.iloc[0]),
        terminal_equity=float(equity.iloc[-1]),
        total_return=total_return,
        cagr=float((equity.iloc[-1] / equity.iloc[0]) ** (1.0 / years) - 1.0),
        volatility=volatility,
        sharpe=float(returns.mean() * ppy / volatility) if volatility > 0 else 0.0,
        max_drawdown=float((equity / equity.cummax() - 1.0).min()),
        trade_count=len(trades),
        total_cost=float(trades["cost"].sum()) if not trades.empty else 0.0,
        same_bar_fill_count=int(fill_dates.isin(decisions).sum()),
        first_fill_date=fill_dates.min().date().isoformat() if len(fill_dates) else None,
        last_fill_date=fill_dates.max().date().isoformat() if len(fill_dates) else None,
    )


def _run(panel: pd.DataFrame, targets: pd.DataFrame, bps: float) -> MultiAssetBacktestResult:
    return run_multi_asset_backtest(
        panel,
        targets[["timestamp", "symbol", "target_weight"]],
        initial_cash=INITIAL_CASH,
        cost_model=_cost_model(bps),
        max_weight_per_asset=1.0,
        allow_leverage=False,
        allow_short=False,
        fractional_shares=True,
        rebalance_band=0.0,
        max_gross_exposure=1.0,
    )


def _cash_result(panel: pd.DataFrame) -> MultiAssetBacktestResult:
    return _run(panel, pd.DataFrame(columns=["timestamp", "symbol", "target_weight"]), 0.0)


def _block_counts(
    strategy: pd.DataFrame,
    benchmarks: Mapping[str, pd.DataFrame],
    block_count: int,
) -> dict[str, int]:
    aligned = strategy.set_index("timestamp")[["equity"]].rename(columns={"equity": "strategy"})
    for name, curve in benchmarks.items():
        aligned = aligned.join(
            curve.set_index("timestamp")[["equity"]].rename(columns={"equity": name}), how="inner"
        )
    if len(aligned) - 1 < block_count or aligned.isna().any().any():
        raise WeeklyDevelopmentEvidenceError("BLOCK_EQUITY_CURVES_DO_NOT_ALIGN")
    counts = {name: 0 for name in benchmarks}
    # Partition one-period return intervals, not equity observations.  Adjacent
    # blocks deliberately share their boundary equity point so every return,
    # including the return across a partition boundary, is counted exactly once.
    for return_positions in np.array_split(np.arange(1, len(aligned)), block_count):
        start_position = int(return_positions[0]) - 1
        end_position = int(return_positions[-1])
        strategy_return = float(
            aligned["strategy"].iloc[end_position] / aligned["strategy"].iloc[start_position] - 1.0
        )
        for name in benchmarks:
            benchmark_return = float(
                aligned[name].iloc[end_position] / aligned[name].iloc[start_position] - 1.0
            )
            counts[name] += int(strategy_return > benchmark_return)
    return counts


def _scenario(
    panel: pd.DataFrame,
    targets: pd.DataFrame,
    *,
    bps: float,
    long_fill_fraction: float,
    block_count: int,
) -> WeeklyScenarioSnapshot:
    engine_targets = targets.rename(columns={"decision_timestamp": "timestamp"}).copy()
    engine_targets["target_weight"] = np.where(
        engine_targets["target_weight"] > 0.0,
        engine_targets["target_weight"] * long_fill_fraction,
        0.0,
    )
    decisions = set(pd.to_datetime(targets["decision_timestamp"], utc=True))
    strategy_result = _run(panel, engine_targets, bps)
    start = pd.Timestamp(DEVELOPMENT_DECISION_START, tz="UTC")
    btc_result = _run(
        panel,
        pd.DataFrame([{"timestamp": start, "symbol": SYMBOL, "target_weight": long_fill_fraction}]),
        bps,
    )
    cash_result = _cash_result(panel)
    benchmark_results = {
        "btc_usdt_buy_and_hold": btc_result,
        "zero_yield_cash": cash_result,
    }
    benchmark_decisions = {start}
    return WeeklyScenarioSnapshot(
        cost_bps_per_side=bps,
        long_fill_fraction=long_fill_fraction,
        strategy=_snapshot(strategy_result, decisions),
        benchmarks={
            name: _snapshot(result, benchmark_decisions)
            for name, result in benchmark_results.items()
        },
        block_outperformance_counts=_block_counts(
            strategy_result.equity_curve,
            {name: result.equity_curve for name, result in benchmark_results.items()},
            block_count,
        ),
    )


def _insufficient(
    spec: WeeklyMomentumSpec, hashes: Mapping[str, str], reason: str
) -> WeeklyDevelopmentVerdict:
    return WeeklyDevelopmentVerdict(
        status="INSUFFICIENT_EVIDENCE",
        strategy_id=str(getattr(spec, "strategy_id", STRATEGY_ID)),
        decision_start=DEVELOPMENT_DECISION_START,
        decision_end=DEVELOPMENT_DECISION_END,
        evidence_end=DEVELOPMENT_EVIDENCE_END,
        evidence_hashes=hashes,
        completed_decisions=0,
        signal_count=0,
        scenarios={},
        reasons=(reason, "DEVELOPMENT_ONLY_CANNOT_AUTHORIZE_PROMOTION_OR_LIVE_EXECUTION"),
    )


def evaluate_weekly_momentum_development(
    data_directory: str | Path,
    spec: WeeklyMomentumSpec,
) -> WeeklyDevelopmentVerdict:
    """Evaluate the one sealed rule against one explicit, cutoff-bound dataset."""

    hashes: dict[str, str] = {}
    try:
        validated = WeeklyMomentumSpec(**spec.canonical_payload())
        if validated.seal() != spec.seal():
            raise WeeklyDevelopmentEvidenceError("SPEC_RECONSTRUCTION_MISMATCH")
        hashes["spec"] = spec.seal()
        records, journal_bytes = _read_journal(Path(data_directory))
        hashes["journal.jsonl"] = sha256_of_bytes(journal_bytes)
        record = _journal_symbol_record(records)
        receipts_digest, rebuilt_rows = _verify_receipts(Path(data_directory), record)
        hashes["receipts.jsonl"] = receipts_digest
        panel, series_digest = _parse_series(Path(data_directory), record, rebuilt_rows)
        hashes[f"series/{SYMBOL}.jsonl"] = series_digest
        hashes["dataset"] = sha256_of_text(canonical_dumps(dict(sorted(hashes.items()))))
    except (AttributeError, TypeError, ValueError) as exc:
        return _insufficient(spec, hashes, str(exc) or type(exc).__name__.upper())

    decision_dates = pd.date_range(
        DEVELOPMENT_DECISION_START, DEVELOPMENT_DECISION_END, freq="7D", tz="UTC"
    )
    evidence_end = pd.Timestamp(DEVELOPMENT_EVIDENCE_END, tz="UTC")
    # A decision is independent evidence only after its entire following
    # Sunday-to-Sunday outcome week is observable. The last sealed decision is
    # executable before the cutoff but right-censored, so it is not counted.
    completed_decisions = int(((decision_dates + pd.Timedelta(days=7)) <= evidence_end).sum())
    try:
        targets = development_weekly_momentum_targets(
            panel,
            spec,
            DEVELOPMENT_DECISION_START,
            DEVELOPMENT_DECISION_END,
        )
        if targets.empty:
            raise WeeklyDevelopmentEvidenceError("WEEKLY_SIGNAL_HAS_NO_INITIAL_STATE")
        policy = spec.development_falsification_policy
        # Independent observations are completed LONG episodes, not order
        # legs or partial fills. A trailing open episode is not completed.
        states = list(targets["signal_state"].astype(str))
        independent_trades = sum(
            left == "LONG" and right == "CASH"
            for left, right in zip(states, states[1:], strict=False)
        )
        minimum_trades = int(policy["minimum_independent_trades"])
        if independent_trades < minimum_trades:
            return WeeklyDevelopmentVerdict(
                status="INSUFFICIENT_EVIDENCE",
                strategy_id=spec.strategy_id,
                decision_start=DEVELOPMENT_DECISION_START,
                decision_end=DEVELOPMENT_DECISION_END,
                evidence_end=DEVELOPMENT_EVIDENCE_END,
                evidence_hashes=hashes,
                completed_decisions=completed_decisions,
                signal_count=len(targets),
                scenarios={},
                reasons=(
                    f"ONLY_{independent_trades}_OF_{minimum_trades}_REQUIRED_CLOSED_LONG_EPISODES",
                    "DEVELOPMENT_ONLY_CANNOT_AUTHORIZE_PROMOTION_OR_LIVE_EXECUTION",
                ),
            )
        block_count = int(policy["contiguous_blocks"])
        scenarios = {
            "normal": _scenario(
                panel,
                targets,
                bps=NORMAL_COST_BPS_PER_SIDE,
                long_fill_fraction=1.0,
                block_count=block_count,
            ),
            "stress_2x_long_fills_50pct": _scenario(
                panel,
                targets,
                bps=STRESS_COST_BPS_PER_SIDE,
                long_fill_fraction=float(spec.cost_policy["stress_long_fill_fraction"]),
                block_count=block_count,
            ),
        }
    except ValueError as exc:
        return WeeklyDevelopmentVerdict(
            status="INSUFFICIENT_EVIDENCE",
            strategy_id=spec.strategy_id,
            decision_start=DEVELOPMENT_DECISION_START,
            decision_end=DEVELOPMENT_DECISION_END,
            evidence_end=DEVELOPMENT_EVIDENCE_END,
            evidence_hashes=hashes,
            completed_decisions=completed_decisions,
            signal_count=0,
            scenarios={},
            reasons=(str(exc), "DEVELOPMENT_ONLY_CANNOT_AUTHORIZE_PROMOTION_OR_LIVE_EXECUTION"),
        )

    normal = scenarios["normal"]
    stress = scenarios["stress_2x_long_fills_50pct"]
    reasons: list[str] = []
    minimum_decisions = int(policy["minimum_completed_decisions"])
    if completed_decisions < minimum_decisions:
        reasons.append(f"ONLY_{completed_decisions}_OF_{minimum_decisions}_REQUIRED_DECISIONS")
    if bool(policy["net_total_return_positive"]) and normal.strategy.total_return <= 0.0:
        reasons.append("NORMAL_NET_TOTAL_RETURN_IS_NOT_POSITIVE")
    for benchmark_id in policy["required_benchmark_ids"]:
        if (
            bool(policy["outperform_each_benchmark"])
            and normal.strategy.total_return <= normal.benchmarks[str(benchmark_id)].total_return
        ):
            reasons.append(f"NORMAL_RETURN_DOES_NOT_EXCEED_{str(benchmark_id).upper()}")
        observed = normal.block_outperformance_counts[str(benchmark_id)]
        minimum = int(policy["minimum_outperforming_blocks"])
        if observed < minimum:
            reasons.append(
                f"OUTPERFORMS_{str(benchmark_id).upper()}_IN_{observed}_OF_{int(policy['contiguous_blocks'])}_BLOCKS"
            )
    maximum_drawdown = float(policy["max_drawdown_abs"])
    if normal.strategy.max_drawdown < -maximum_drawdown:
        reasons.append(f"NORMAL_MAX_DRAWDOWN_EXCEEDS_{maximum_drawdown:.6f}_ABS")
    if stress.strategy.total_return < float(policy["stress_total_return_min"]):
        reasons.append("STRESS_2X_RETURN_IS_NEGATIVE")
    if normal.strategy.same_bar_fill_count or stress.strategy.same_bar_fill_count:
        reasons.append("SAME_BAR_FILL_DETECTED")
    status: VerdictStatus = "NO_GO" if reasons else "INSUFFICIENT_EVIDENCE"
    if not reasons:
        reasons.append("DEVELOPMENT_RULE_NOT_FALSIFIED_BUT_PROSPECTIVE_EVIDENCE_IS_REQUIRED")
    reasons.extend(
        (
            "PBO_NOT_IDENTIFIABLE_FOR_SINGLE_TRIAL",
            "ONE_ASSET_POLICY_CONFLICTS_WITH_GATE4_DIVERSIFICATION",
            "DEVELOPMENT_ONLY_CANNOT_AUTHORIZE_PROMOTION_OR_LIVE_EXECUTION",
        )
    )
    return WeeklyDevelopmentVerdict(
        status=status,
        strategy_id=spec.strategy_id,
        decision_start=DEVELOPMENT_DECISION_START,
        decision_end=DEVELOPMENT_DECISION_END,
        evidence_end=DEVELOPMENT_EVIDENCE_END,
        evidence_hashes=hashes,
        completed_decisions=completed_decisions,
        signal_count=len(targets),
        scenarios=scenarios,
        reasons=tuple(reasons),
    )


__all__ = [
    "NORMAL_COST_BPS_PER_SIDE",
    "STRESS_COST_BPS_PER_SIDE",
    "WeeklyDevelopmentVerdict",
    "WeeklyPerformanceSnapshot",
    "WeeklyScenarioSnapshot",
    "evaluate_weekly_momentum_development",
]
