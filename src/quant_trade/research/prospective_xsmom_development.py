"""Offline, fail-closed development evaluator for the sealed XSMOM trial.

The current XSMOM declaration deliberately does *not* activate an economic
development window.  Consequently a real development bundle is rejected from
its manifest before any market-data file is opened.  The complete evaluator is
still exercised with explicitly labelled synthetic artifacts so that the data
contract, Friday-only execution, venue filters, symbol-specific costs and
benchmark accounting can be reviewed before a future independently sealed
activation.

There is no loader for remote resources, strategy registry, broker adapter or
order route in this module.  Its verdict type cannot represent ``PASS`` and can
never authorize promotion, live execution or real money.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, fields
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

import pandas as pd

from quant_trade.data.binance_symbol_rules import (
    BinanceSpotSymbolRulesLedger,
    SymbolRuleAvailability,
)
from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_bytes, sha256_of_text
from quant_trade.research.prospective_xsmom import (
    MARKET,
    SPEC_SEAL,
    STRATEGY_ID,
    VENUE,
    XSMOMDecision,
    XSMOMSpec,
    build_xsmom_decision,
)
from quant_trade.research.prospective_xsmom import (
    REQUIRED_COLUMNS as SIGNAL_REQUIRED_COLUMNS,
)

VerdictStatus = Literal["NO_GO", "INSUFFICIENT_EVIDENCE"]

SCHEMA_VERSION = 1
# Synthetic contract accounting is denominated in Binance's quote asset. It
# intentionally does not assert USDT == USD. Real USD economics remain blocked
# until a causal USDT/USD conversion artifact is specified and bound.
INITIAL_CAPITAL_QUOTE_USDT = 200.0
MAX_SYMBOL_RULE_AGE = timedelta(days=1)
HOLDOUT_START_UTC = pd.Timestamp("2023-11-29T00:00:00Z")
ARTIFACT_FILES = (
    "selection_panel.jsonl",
    "execution_bars.jsonl",
    "execution_terms.jsonl",
)
REAL_ARTIFACT_KIND = "CAUSAL_DEVELOPMENT"
SYNTHETIC_ARTIFACT_KIND = "SYNTHETIC_TEST_ONLY"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_VENUE_SYMBOL_RE = re.compile(r"^[A-Z0-9]+USDT$")

EXECUTION_BAR_COLUMNS = (
    "timestamp",
    "bar_closed_at_utc",
    "instrument_id",
    "cmc_id",
    "venue_symbol",
    "venue",
    "market",
    "open",
    "open_observed_at_utc",
    "mark_price",
    "mark_observed_at_utc",
    "data_status",
    "tradable",
    "market_event",
    "market_event_observed_at_utc",
)
EXECUTION_TERM_COLUMNS = (
    "execution_timestamp_utc",
    "instrument_id",
    "cmc_id",
    "venue_symbol",
    "venue",
    "market",
    "observed_at_utc",
    "fee_observed_at_utc",
    "valid_from_utc",
    "valid_to_utc",
    "cost_sample_end_utc",
    "tick_size",
    "quantity_step",
    "min_quantity",
    "max_quantity",
    "min_notional_quote_usdt",
    "max_notional_quote_usdt",
    "taker_fee_bps",
    "spread_cost_bps_p75",
    "impact_cost_bps_p75",
    "rules_source_sha256",
    "fee_source_sha256",
    "cost_source_sha256",
)
_ALLOWED_DATA_STATUS = frozenset({"VALID", "GAP", "HALT"})
_ALLOWED_MARKET_EVENTS = frozenset({"NONE", "HALT", "DELISTING_ANNOUNCED", "DELISTING_CONFIRMED"})
_PORTFOLIO_KEYS = frozenset({"candidate_xsmom", "liquidity_control", "btc_95_cash_5", "btc_100"})
_BLOCK_BENCHMARK_KEYS = frozenset({"liquidity_control", "btc_95_cash_5", "btc_100"})
_SCENARIO_KEYS = frozenset({"normal", "stress_2x_costs_50pct_fills"})
_SCENARIO_PARAMETERS = frozenset({(1.0, 1.0), (2.0, 0.5)})
_EXECUTION_SIDES = frozenset({"buy", "sell", "terminal_write_down"})
_EXECUTION_STATUSES = frozenset(
    {"FILLED", "PARTIALLY_FILLED_EXPIRED", "REFUSED", "EXPIRED", "WRITE_DOWN_ZERO"}
)
_CMC_INSTRUMENT_RE = re.compile(r"^CMC:[1-9][0-9]*$")


class XSMOMDevelopmentEvidenceError(ValueError):
    """An artifact or causal-contract violation converted to a safe verdict."""


def _clean_text(name: str, value: Any, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or value != value.strip() or "\n" in value or "\r" in value:
        raise ValueError(f"{name} must be clean single-line text")
    if not allow_empty and not value:
        raise ValueError(f"{name} must be non-empty")
    return value


def _finite_number(name: str, value: Any, *, minimum: float | None = None) -> float:
    if type(value) not in {int, float} or not math.isfinite(float(value)):
        raise ValueError(f"{name} must be an actual finite number, not bool")
    observed = float(value)
    if minimum is not None and observed < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return observed


def _nonnegative_int(name: str, value: Any) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be an actual non-negative integer")
    return value


def _utc(name: str, value: Any) -> pd.Timestamp:
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise XSMOMDevelopmentEvidenceError(f"{name.upper()}_IS_NOT_A_TIMESTAMP") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != pd.Timedelta(0):
        raise XSMOMDevelopmentEvidenceError(f"{name.upper()}_MUST_BE_TIMEZONE_AWARE_UTC")
    return parsed


def _sha(name: str, value: Any) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise XSMOMDevelopmentEvidenceError(f"{name.upper()}_MUST_BE_LOWERCASE_SHA256")
    return value


@dataclass(frozen=True)
class XSMOMDevelopmentManifest:
    """Trusted envelope read before any development data file."""

    schema_version: int
    artifact_kind: str
    strategy_id: str
    strategy_spec_seal: str
    venue: str
    market: str
    decision_start_utc: str
    decision_end_utc: str
    evidence_end_utc: str
    holdout_start_utc: str
    contains_holdout_data: bool
    causal_verification_status: str
    evaluator_network_access_required: bool
    independent_preregistration_commit_sha: str
    builder_commit_sha: str
    file_sha256: Mapping[str, str]
    row_counts: Mapping[str, int]
    source_artifact_sha256: Mapping[str, str]

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise XSMOMDevelopmentEvidenceError("MANIFEST_SCHEMA_VERSION_IS_NOT_SUPPORTED")
        if self.artifact_kind not in {REAL_ARTIFACT_KIND, SYNTHETIC_ARTIFACT_KIND}:
            raise XSMOMDevelopmentEvidenceError("MANIFEST_ARTIFACT_KIND_IS_NOT_ALLOWED")
        if self.strategy_id != STRATEGY_ID or self.strategy_spec_seal != SPEC_SEAL:
            raise XSMOMDevelopmentEvidenceError("MANIFEST_DOES_NOT_BIND_THE_SEALED_XSMOM_TRIAL")
        if self.venue != VENUE or self.market != MARKET:
            raise XSMOMDevelopmentEvidenceError("MANIFEST_IS_NOT_BINANCE_SPOT_ONLY")
        if type(self.contains_holdout_data) is not bool or self.contains_holdout_data:
            raise XSMOMDevelopmentEvidenceError("MANIFEST_CONTAINS_OR_AMBIGUOUSLY_LABELS_HOLDOUT")
        if (
            type(self.evaluator_network_access_required) is not bool
            or self.evaluator_network_access_required
        ):
            raise XSMOMDevelopmentEvidenceError("EVALUATOR_MUST_NOT_REQUIRE_NETWORK_ACCESS")
        if self.causal_verification_status != "VERIFIED_CAUSAL":
            raise XSMOMDevelopmentEvidenceError("ARTIFACT_IS_NOT_MARKED_VERIFIED_CAUSAL")

        start = _utc("decision_start_utc", self.decision_start_utc)
        end = _utc("decision_end_utc", self.decision_end_utc)
        evidence_end = _utc("evidence_end_utc", self.evidence_end_utc)
        holdout = _utc("holdout_start_utc", self.holdout_start_utc)
        if holdout != HOLDOUT_START_UTC:
            raise XSMOMDevelopmentEvidenceError("MANIFEST_HOLDOUT_BOUNDARY_IS_NOT_SEALED")
        if start.dayofweek != 3 or start != start.normalize():
            raise XSMOMDevelopmentEvidenceError("DECISION_START_MUST_BE_THURSDAY_00_00_UTC")
        if end.dayofweek != 3 or end != end.normalize() or end < start:
            raise XSMOMDevelopmentEvidenceError("DECISION_END_MUST_BE_THURSDAY_00_00_UTC")
        if (end - start) % pd.Timedelta(days=7) != pd.Timedelta(0):
            raise XSMOMDevelopmentEvidenceError("DECISION_WINDOW_MUST_USE_EXACT_SEVEN_DAY_STEPS")
        if evidence_end < end + pd.Timedelta(days=8):
            raise XSMOMDevelopmentEvidenceError("LAST_DECISION_LACKS_A_COMPLETE_WEEKLY_OUTCOME")
        if evidence_end >= holdout or end >= holdout:
            raise XSMOMDevelopmentEvidenceError("MANIFEST_REACHES_THE_SEALED_HOLDOUT")

        if set(self.file_sha256) != set(ARTIFACT_FILES):
            raise XSMOMDevelopmentEvidenceError("MANIFEST_FILE_HASH_SET_IS_NOT_EXACT")
        if set(self.row_counts) != set(ARTIFACT_FILES):
            raise XSMOMDevelopmentEvidenceError("MANIFEST_ROW_COUNT_SET_IS_NOT_EXACT")
        frozen_hashes: dict[str, str] = {}
        frozen_counts: dict[str, int] = {}
        for filename in ARTIFACT_FILES:
            frozen_hashes[filename] = _sha(filename, self.file_sha256[filename])
            count = self.row_counts[filename]
            if isinstance(count, bool) or not isinstance(count, int) or count < 1:
                raise XSMOMDevelopmentEvidenceError(
                    f"{filename.upper()}_ROW_COUNT_MUST_BE_A_POSITIVE_INTEGER"
                )
            frozen_counts[filename] = count
        required_sources = {
            "identity_and_classification",
            "binance_daily_bars",
            "binance_symbol_rules",
            "binance_account_fees",
            "symbol_cost_model",
        }
        if set(self.source_artifact_sha256) != required_sources:
            raise XSMOMDevelopmentEvidenceError("MANIFEST_SOURCE_ARTIFACT_SET_IS_NOT_EXACT")
        frozen_sources = {
            name: _sha(name, value) for name, value in self.source_artifact_sha256.items()
        }
        for name, value in (
            ("builder_commit_sha", self.builder_commit_sha),
            ("independent_preregistration_commit_sha", self.independent_preregistration_commit_sha),
        ):
            if not isinstance(value, str) or _COMMIT_RE.fullmatch(value) is None:
                raise XSMOMDevelopmentEvidenceError(f"{name.upper()}_MUST_BE_A_GIT_SHA1")
        if self.artifact_kind == REAL_ARTIFACT_KIND and (
            self.independent_preregistration_commit_sha == "0" * 40
            or self.builder_commit_sha == "0" * 40
        ):
            raise XSMOMDevelopmentEvidenceError("REAL_ARTIFACT_REQUIRES_NONZERO_COMMIT_PROVENANCE")
        object.__setattr__(self, "file_sha256", MappingProxyType(frozen_hashes))
        object.__setattr__(self, "row_counts", MappingProxyType(frozen_counts))
        object.__setattr__(self, "source_artifact_sha256", MappingProxyType(frozen_sources))

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> XSMOMDevelopmentManifest:
        expected = {item.name for item in fields(cls)}
        if set(raw) != expected:
            raise XSMOMDevelopmentEvidenceError("MANIFEST_FIELDS_ARE_NOT_EXACT")
        return cls(**dict(raw))

    @property
    def decision_start(self) -> pd.Timestamp:
        return _utc("decision_start_utc", self.decision_start_utc)

    @property
    def decision_end(self) -> pd.Timestamp:
        return _utc("decision_end_utc", self.decision_end_utc)

    @property
    def evidence_end(self) -> pd.Timestamp:
        return _utc("evidence_end_utc", self.evidence_end_utc)


@dataclass(frozen=True)
class XSMOMDevelopmentExecution:
    portfolio: str
    decision_timestamp: str
    execution_timestamp: str
    instrument_id: str
    venue_symbol: str
    side: str
    requested_quantity: float
    filled_quantity: float
    refused_quantity: float
    open_price: float | None
    fill_price: float | None
    fee_quote_usdt: float
    adverse_price_cost_quote_usdt: float
    status: str
    reason: str

    def __post_init__(self) -> None:
        if self.portfolio not in _PORTFOLIO_KEYS:
            raise ValueError("execution portfolio is not one of the four sealed books")
        decision_text = _clean_text("decision_timestamp", self.decision_timestamp)
        execution_text = _clean_text("execution_timestamp", self.execution_timestamp)
        decision = _utc("decision_timestamp", decision_text)
        execution = _utc("execution_timestamp", execution_text)
        if decision != decision.normalize() or execution != execution.normalize():
            raise ValueError("execution timestamps must be exact 00:00 UTC boundaries")
        if (
            not isinstance(self.instrument_id, str)
            or _CMC_INSTRUMENT_RE.fullmatch(self.instrument_id) is None
        ):
            raise ValueError("execution instrument_id must be CMC:<positive integer>")
        if (
            not isinstance(self.venue_symbol, str)
            or _VENUE_SYMBOL_RE.fullmatch(self.venue_symbol) is None
        ):
            raise ValueError("execution venue_symbol must name a non-empty USDT base")
        if self.side not in _EXECUTION_SIDES:
            raise ValueError("execution side is invalid")
        if self.status not in _EXECUTION_STATUSES:
            raise ValueError("execution status is invalid")
        requested = _finite_number("requested_quantity", self.requested_quantity, minimum=0.0)
        filled = _finite_number("filled_quantity", self.filled_quantity, minimum=0.0)
        refused = _finite_number("refused_quantity", self.refused_quantity, minimum=0.0)
        fee = _finite_number("fee_quote_usdt", self.fee_quote_usdt, minimum=0.0)
        adverse = _finite_number(
            "adverse_price_cost_quote_usdt",
            self.adverse_price_cost_quote_usdt,
            minimum=0.0,
        )
        if not math.isclose(requested, filled + refused, rel_tol=1e-9, abs_tol=1e-9):
            raise ValueError("requested quantity must equal filled plus refused quantity")
        for name in ("open_price", "fill_price"):
            value = getattr(self, name)
            if value is not None:
                _finite_number(name, value, minimum=0.0)
        reason = _clean_text("execution reason", self.reason, allow_empty=True)

        if self.status == "WRITE_DOWN_ZERO":
            if (
                self.side != "terminal_write_down"
                or decision != execution
                or requested <= 0.0
                or not math.isclose(filled, requested)
                or refused != 0.0
                or self.open_price is not None
                or self.fill_price != 0.0
                or fee != 0.0
                or not reason
            ):
                raise ValueError("terminal write-down fields are inconsistent")
            return
        if self.side == "terminal_write_down":
            raise ValueError("terminal_write_down side requires WRITE_DOWN_ZERO status")
        if (
            decision.dayofweek != 3
            or execution.dayofweek != 4
            or execution != decision + pd.Timedelta(days=1)
        ):
            raise ValueError("ordinary execution must be exact Thursday-to-Friday t+1")
        if self.status in {"FILLED", "PARTIALLY_FILLED_EXPIRED"}:
            if (
                filled <= 0.0
                or self.open_price is None
                or self.fill_price is None
                or self.open_price <= 0.0
                or self.fill_price <= 0.0
            ):
                raise ValueError("filled execution requires positive quantity/open/fill")
            if self.status == "FILLED" and (refused != 0.0 or reason):
                raise ValueError("FILLED execution cannot refuse quantity or carry a reason")
            if self.status == "PARTIALLY_FILLED_EXPIRED" and (refused <= 0.0 or not reason):
                raise ValueError("partial expired execution requires refusal and reason")
        elif (
            filled != 0.0
            or not math.isclose(refused, requested)
            or self.open_price is not None
            or self.fill_price is not None
            or fee != 0.0
            or adverse != 0.0
            or not reason
        ):
            raise ValueError("refused/expired execution fields are inconsistent")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class XSMOMDevelopmentPerformance:
    initial_equity_quote_usdt: float
    terminal_equity_quote_usdt: float
    total_return: float
    annualized_weekly_sharpe: float
    max_drawdown: float
    total_cost_quote_usdt: float
    execution_count: int
    filled_count: int
    partial_count: int
    refused_or_expired_count: int
    same_boundary_fill_count: int

    def __post_init__(self) -> None:
        initial = _finite_number(
            "initial_equity_quote_usdt", self.initial_equity_quote_usdt, minimum=0.0
        )
        terminal = _finite_number(
            "terminal_equity_quote_usdt", self.terminal_equity_quote_usdt, minimum=0.0
        )
        if initial <= 0.0 or terminal <= 0.0:
            raise ValueError("performance equity must be strictly positive")
        total_return = _finite_number("total_return", self.total_return)
        if not math.isclose(
            total_return,
            terminal / initial - 1.0,
            rel_tol=1e-10,
            abs_tol=1e-12,
        ):
            raise ValueError("performance total_return disagrees with terminal/initial equity")
        _finite_number("annualized_weekly_sharpe", self.annualized_weekly_sharpe)
        drawdown = _finite_number("max_drawdown", self.max_drawdown)
        if not -1.0 <= drawdown <= 0.0:
            raise ValueError("performance max_drawdown must be in [-1, 0]")
        _finite_number("total_cost_quote_usdt", self.total_cost_quote_usdt, minimum=0.0)
        counts = {
            name: _nonnegative_int(name, getattr(self, name))
            for name in (
                "execution_count",
                "filled_count",
                "partial_count",
                "refused_or_expired_count",
                "same_boundary_fill_count",
            )
        }
        if any(value > counts["execution_count"] for value in counts.values()):
            raise ValueError("performance sub-count cannot exceed execution_count")
        if (
            counts["filled_count"] + counts["partial_count"] + counts["refused_or_expired_count"]
            > counts["execution_count"]
        ):
            raise ValueError("performance execution status counts exceed execution_count")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class XSMOMDevelopmentScenario:
    cost_multiplier: float
    fill_fraction: float
    performance: Mapping[str, XSMOMDevelopmentPerformance]
    block_outperformance_counts: Mapping[str, int]
    executions: tuple[XSMOMDevelopmentExecution, ...]

    def __post_init__(self) -> None:
        cost_multiplier = _finite_number("cost_multiplier", self.cost_multiplier)
        fill_fraction = _finite_number("fill_fraction", self.fill_fraction)
        if (cost_multiplier, fill_fraction) not in _SCENARIO_PARAMETERS:
            raise ValueError("scenario must be exactly normal 1x/100% or stress 2x/50%")
        if not isinstance(self.performance, Mapping) or set(self.performance) != _PORTFOLIO_KEYS:
            raise ValueError("scenario performance must contain the exact four sealed books")
        if any(
            not isinstance(snapshot, XSMOMDevelopmentPerformance)
            for snapshot in self.performance.values()
        ):
            raise ValueError("scenario performance values must be typed snapshots")
        if (
            not isinstance(self.block_outperformance_counts, Mapping)
            or set(self.block_outperformance_counts) != _BLOCK_BENCHMARK_KEYS
        ):
            raise ValueError("scenario block counts must contain the exact three benchmarks")
        for name, value in self.block_outperformance_counts.items():
            count = _nonnegative_int(f"block_outperformance_counts.{name}", value)
            if count > 4:
                raise ValueError("block outperformance count must be in [0, 4]")
        if not isinstance(self.executions, tuple) or any(
            not isinstance(execution, XSMOMDevelopmentExecution) for execution in self.executions
        ):
            raise ValueError("scenario executions must be a tuple of typed executions")
        for portfolio, snapshot in self.performance.items():
            executions = tuple(item for item in self.executions if item.portfolio == portfolio)
            observed = {
                "execution_count": len(executions),
                "filled_count": sum(item.status == "FILLED" for item in executions),
                "partial_count": sum(
                    item.status == "PARTIALLY_FILLED_EXPIRED" for item in executions
                ),
                "refused_or_expired_count": sum(
                    item.status in {"REFUSED", "EXPIRED"} for item in executions
                ),
                "same_boundary_fill_count": sum(
                    item.side != "terminal_write_down"
                    and item.filled_quantity > 0
                    and item.decision_timestamp == item.execution_timestamp
                    for item in executions
                ),
            }
            if any(getattr(snapshot, name) != value for name, value in observed.items()):
                raise ValueError(f"{portfolio} performance counts disagree with executions")
            modeled_cost = sum(
                item.fee_quote_usdt + item.adverse_price_cost_quote_usdt
                for item in executions
                if item.side != "terminal_write_down"
            )
            if not math.isclose(
                snapshot.total_cost_quote_usdt,
                modeled_cost,
                rel_tol=1e-9,
                abs_tol=1e-9,
            ):
                raise ValueError(f"{portfolio} performance cost disagrees with executions")
        object.__setattr__(self, "performance", MappingProxyType(dict(self.performance)))
        object.__setattr__(
            self,
            "block_outperformance_counts",
            MappingProxyType(dict(self.block_outperformance_counts)),
        )
        object.__setattr__(self, "executions", tuple(self.executions))

    def to_dict(self) -> dict[str, Any]:
        return {
            "cost_multiplier": self.cost_multiplier,
            "fill_fraction": self.fill_fraction,
            "performance": {
                name: snapshot.to_dict() for name, snapshot in sorted(self.performance.items())
            },
            "block_outperformance_counts": dict(sorted(self.block_outperformance_counts.items())),
            "executions": [execution.to_dict() for execution in self.executions],
        }


@dataclass(frozen=True)
class XSMOMDevelopmentVerdict:
    status: VerdictStatus
    strategy_id: str
    evidence_hashes: Mapping[str, str]
    decision_count: int
    completed_weekly_periods: int
    cohort_digests: tuple[str, ...]
    scenarios: Mapping[str, XSMOMDevelopmentScenario]
    reasons: tuple[str, ...]
    schema_version: int = SCHEMA_VERSION
    development_only: bool = True
    promotion_authorized: bool = False
    live_execution_authorized: bool = False
    real_money_authorized: bool = False

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"XSMOM development schema_version must be {SCHEMA_VERSION}")
        if self.status not in {"NO_GO", "INSUFFICIENT_EVIDENCE"}:
            raise ValueError("XSMOM development verdicts can never be PASS")
        if self.strategy_id != STRATEGY_ID:
            raise ValueError("XSMOM development verdict strategy_id is sealed")
        if type(self.development_only) is not bool or not self.development_only:
            raise ValueError("XSMOM development verdict must remain development_only")
        if any(
            type(value) is not bool
            for value in (
                self.promotion_authorized,
                self.live_execution_authorized,
                self.real_money_authorized,
            )
        ):
            raise ValueError("XSMOM authorization fields must be actual booleans")
        if (
            self.promotion_authorized
            or self.live_execution_authorized
            or self.real_money_authorized
        ):
            raise ValueError("XSMOM development evidence cannot authorize promotion or money")

        decision_count = _nonnegative_int("decision_count", self.decision_count)
        completed = _nonnegative_int("completed_weekly_periods", self.completed_weekly_periods)
        if completed > decision_count:
            raise ValueError("completed_weekly_periods cannot exceed decision_count")
        if not isinstance(self.evidence_hashes, Mapping):
            raise ValueError("evidence_hashes must be a mapping")
        frozen_hashes: dict[str, str] = {}
        for name, digest in self.evidence_hashes.items():
            clean_name = _clean_text("evidence hash name", name)
            frozen_hashes[clean_name] = _sha(clean_name, digest)
        if not isinstance(self.cohort_digests, tuple):
            raise ValueError("cohort_digests must be an immutable tuple")
        frozen_cohorts = tuple(
            _sha(f"cohort_digests[{index}]", digest)
            for index, digest in enumerate(self.cohort_digests)
        )
        if not isinstance(self.scenarios, Mapping):
            raise ValueError("scenarios must be a mapping")
        frozen_scenarios = dict(self.scenarios)
        if frozen_scenarios:
            if set(frozen_scenarios) != _SCENARIO_KEYS:
                raise ValueError("non-empty verdict requires the exact normal and stress scenarios")
            if any(
                not isinstance(scenario, XSMOMDevelopmentScenario)
                for scenario in frozen_scenarios.values()
            ):
                raise ValueError("verdict scenarios must be typed XSMOM scenarios")
            if (
                frozen_scenarios["normal"].cost_multiplier,
                frozen_scenarios["normal"].fill_fraction,
            ) != (1.0, 1.0) or (
                frozen_scenarios["stress_2x_costs_50pct_fills"].cost_multiplier,
                frozen_scenarios["stress_2x_costs_50pct_fills"].fill_fraction,
            ) != (2.0, 0.5):
                raise ValueError("verdict scenario names do not match their sealed parameters")
            if decision_count < 4 or completed != decision_count:
                raise ValueError("evaluated verdict requires at least four completed decisions")
            if len(frozen_cohorts) != decision_count:
                raise ValueError("evaluated verdict requires one cohort digest per decision")
            if not frozen_hashes:
                raise ValueError("evaluated verdict requires content-addressed evidence")
        elif decision_count or completed or frozen_cohorts:
            raise ValueError("unevaluated verdict cannot claim decisions or cohort digests")

        if not isinstance(self.reasons, tuple) or not self.reasons:
            raise ValueError("XSMOM development verdict requires at least one reason")
        frozen_reasons = tuple(
            _clean_text(f"reasons[{index}]", reason) for index, reason in enumerate(self.reasons)
        )
        if len(frozen_reasons) != len(set(frozen_reasons)):
            raise ValueError("XSMOM development reasons must be unique")
        object.__setattr__(self, "evidence_hashes", MappingProxyType(frozen_hashes))
        object.__setattr__(self, "cohort_digests", frozen_cohorts)
        object.__setattr__(self, "scenarios", MappingProxyType(frozen_scenarios))
        object.__setattr__(self, "reasons", frozen_reasons)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "strategy_id": self.strategy_id,
            "evidence_hashes": dict(sorted(self.evidence_hashes.items())),
            "decision_count": self.decision_count,
            "completed_weekly_periods": self.completed_weekly_periods,
            "cohort_digests": list(self.cohort_digests),
            "scenarios": {
                name: scenario.to_dict() for name, scenario in sorted(self.scenarios.items())
            },
            "reasons": list(self.reasons),
            "development_only": self.development_only,
            "promotion_authorized": self.promotion_authorized,
            "live_execution_authorized": self.live_execution_authorized,
            "real_money_authorized": self.real_money_authorized,
        }

    def report_sha256(self) -> str:
        return sha256_of_text(canonical_dumps(self.to_dict()))


def _insufficient(
    spec: Any,
    evidence_hashes: Mapping[str, str],
    *reasons: str,
) -> XSMOMDevelopmentVerdict:
    return XSMOMDevelopmentVerdict(
        status="INSUFFICIENT_EVIDENCE",
        strategy_id=STRATEGY_ID,
        evidence_hashes=evidence_hashes,
        decision_count=0,
        completed_weekly_periods=0,
        cohort_digests=(),
        scenarios={},
        reasons=(*reasons, "DEVELOPMENT_ONLY_CANNOT_AUTHORIZE_PROMOTION_OR_REAL_MONEY"),
    )


def _read_manifest(root: Path) -> tuple[XSMOMDevelopmentManifest, bytes]:
    path = root / "manifest.json"
    try:
        payload = path.read_bytes()
        raw = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise XSMOMDevelopmentEvidenceError("MANIFEST_MISSING_OR_INVALID") from exc
    if not isinstance(raw, dict):
        raise XSMOMDevelopmentEvidenceError("MANIFEST_MUST_BE_A_JSON_OBJECT")
    canonical = (canonical_dumps(raw) + "\n").encode("utf-8")
    if payload != canonical:
        raise XSMOMDevelopmentEvidenceError("MANIFEST_BYTES_ARE_NOT_CANONICAL_JSON")
    return XSMOMDevelopmentManifest.from_mapping(raw), payload


def _read_artifact_file(
    root: Path,
    filename: str,
    expected_sha256: str,
    expected_rows: int,
) -> tuple[list[dict[str, Any]], bytes]:
    try:
        payload = (root / filename).read_bytes()
    except OSError as exc:
        raise XSMOMDevelopmentEvidenceError(f"{filename.upper()}_MISSING_OR_UNREADABLE") from exc
    if sha256_of_bytes(payload) != expected_sha256:
        raise XSMOMDevelopmentEvidenceError(f"{filename.upper()}_SHA256_MISMATCH")
    rows: list[dict[str, Any]] = []
    try:
        for line in payload.decode("utf-8").splitlines():
            if not line:
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise TypeError("row is not an object")
            rows.append(row)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise XSMOMDevelopmentEvidenceError(f"{filename.upper()}_IS_NOT_JSONL") from exc
    if len(rows) != expected_rows:
        raise XSMOMDevelopmentEvidenceError(f"{filename.upper()}_ROW_COUNT_MISMATCH")
    canonical = ("".join(canonical_dumps(row) + "\n" for row in rows)).encode("utf-8")
    if payload != canonical:
        raise XSMOMDevelopmentEvidenceError(f"{filename.upper()}_BYTES_ARE_NOT_CANONICAL_JSONL")
    return rows, payload


def _require_columns(frame: pd.DataFrame, required: Sequence[str], label: str) -> None:
    missing = sorted(set(required).difference(frame.columns))
    if missing:
        raise XSMOMDevelopmentEvidenceError(f"{label}_MISSING_COLUMNS_{'_'.join(missing)}")


def _normalise_selection(
    rows: list[dict[str, Any]], manifest: XSMOMDevelopmentManifest
) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    _require_columns(frame, SIGNAL_REQUIRED_COLUMNS, "SELECTION_PANEL")
    for name in (
        "timestamp",
        "bar_closed_at_utc",
        "venue_symbol_bound_at_utc",
        "universe_observed_at_utc",
        "classification_public_known_at_utc",
        "classification_valid_from_utc",
        "symbol_rules_observed_at_utc",
    ):
        frame[name] = pd.to_datetime(frame[name], utc=True, errors="coerce")
        if frame[name].isna().any():
            raise XSMOMDevelopmentEvidenceError(f"SELECTION_{name.upper()}_IS_INVALID")
    raw_valid_to = frame["classification_valid_to_utc"].copy()
    frame["classification_valid_to_utc"] = pd.to_datetime(raw_valid_to, utc=True, errors="coerce")
    if (raw_valid_to.notna() & frame["classification_valid_to_utc"].isna()).any():
        raise XSMOMDevelopmentEvidenceError("SELECTION_CLASSIFICATION_VALID_TO_IS_INVALID")
    if frame.duplicated(["instrument_id", "timestamp"]).any():
        raise XSMOMDevelopmentEvidenceError("SELECTION_PANEL_HAS_DUPLICATE_ID_TIMESTAMP")
    if not frame["timestamp"].dt.normalize().eq(frame["timestamp"]).all():
        raise XSMOMDevelopmentEvidenceError("SELECTION_BARS_MUST_START_AT_00_00_UTC")
    if not frame["bar_closed_at_utc"].eq(frame["timestamp"] + pd.Timedelta(days=1)).all():
        raise XSMOMDevelopmentEvidenceError("SELECTION_BAR_CLOSE_BOUNDARY_IS_INVALID")
    if (frame["bar_closed_at_utc"] > manifest.decision_end).any():
        raise XSMOMDevelopmentEvidenceError("SELECTION_PANEL_CONTAINS_POST_DECISION_INFORMATION")
    availability = (
        "venue_symbol_bound_at_utc",
        "universe_observed_at_utc",
        "classification_public_known_at_utc",
        "symbol_rules_observed_at_utc",
    )
    if any((frame[name] > frame["bar_closed_at_utc"]).any() for name in availability):
        raise XSMOMDevelopmentEvidenceError("SELECTION_FACT_WAS_NOT_KNOWN_BY_ITS_BAR_CLOSE")
    return frame.sort_values(["timestamp", "instrument_id"]).reset_index(drop=True)


def _normalise_execution_bars(
    rows: list[dict[str, Any]], manifest: XSMOMDevelopmentManifest
) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    _require_columns(frame, EXECUTION_BAR_COLUMNS, "EXECUTION_BARS")
    for name in ("timestamp", "bar_closed_at_utc"):
        frame[name] = pd.to_datetime(frame[name], utc=True, errors="coerce")
        if frame[name].isna().any():
            raise XSMOMDevelopmentEvidenceError(f"EXECUTION_{name.upper()}_IS_INVALID")
    for name in ("open_observed_at_utc", "mark_observed_at_utc", "market_event_observed_at_utc"):
        raw = frame[name].copy()
        frame[name] = pd.to_datetime(raw, utc=True, errors="coerce")
        if (raw.notna() & frame[name].isna()).any():
            raise XSMOMDevelopmentEvidenceError(f"EXECUTION_{name.upper()}_IS_INVALID")
    if frame.duplicated(["instrument_id", "timestamp"]).any():
        raise XSMOMDevelopmentEvidenceError("EXECUTION_BARS_HAVE_DUPLICATE_ID_TIMESTAMP")
    if not frame["timestamp"].dt.normalize().eq(frame["timestamp"]).all():
        raise XSMOMDevelopmentEvidenceError("EXECUTION_BARS_MUST_START_AT_00_00_UTC")
    if not frame["bar_closed_at_utc"].eq(frame["timestamp"] + pd.Timedelta(days=1)).all():
        raise XSMOMDevelopmentEvidenceError("EXECUTION_BAR_CLOSE_BOUNDARY_IS_INVALID")
    if (frame["timestamp"] > manifest.evidence_end).any():
        raise XSMOMDevelopmentEvidenceError("EXECUTION_BARS_REACH_BEYOND_EVIDENCE_CUTOFF")
    if not frame["venue"].eq(VENUE).all() or not frame["market"].eq(MARKET).all():
        raise XSMOMDevelopmentEvidenceError("EXECUTION_BARS_ARE_NOT_BINANCE_SPOT_ONLY")
    if not frame["data_status"].isin(_ALLOWED_DATA_STATUS).all():
        raise XSMOMDevelopmentEvidenceError("EXECUTION_DATA_STATUS_IS_NOT_ALLOWED")
    if not frame["market_event"].isin(_ALLOWED_MARKET_EVENTS).all():
        raise XSMOMDevelopmentEvidenceError("EXECUTION_MARKET_EVENT_IS_NOT_ALLOWED")
    if any(type(value) is not bool for value in frame["tradable"]):
        raise XSMOMDevelopmentEvidenceError("EXECUTION_TRADABLE_MUST_BE_AN_ACTUAL_BOOLEAN")
    for row in frame.itertuples(index=False):
        if isinstance(row.cmc_id, bool) or not isinstance(row.cmc_id, int) or row.cmc_id < 1:
            raise XSMOMDevelopmentEvidenceError("EXECUTION_CMC_ID_MUST_BE_POSITIVE_INTEGER")
        if row.instrument_id != f"CMC:{row.cmc_id}":
            raise XSMOMDevelopmentEvidenceError("EXECUTION_INSTRUMENT_ID_IS_NOT_STABLE_CMC_ID")
        if (
            not isinstance(row.venue_symbol, str)
            or _VENUE_SYMBOL_RE.fullmatch(row.venue_symbol) is None
        ):
            raise XSMOMDevelopmentEvidenceError("EXECUTION_VENUE_SYMBOL_IS_INVALID")
    if frame.duplicated(["timestamp", "venue_symbol"]).any():
        raise XSMOMDevelopmentEvidenceError("EXECUTION_VENUE_SYMBOL_BINDS_MULTIPLE_IDENTITIES")
    for name in ("open", "mark_price"):
        frame[name] = pd.to_numeric(frame[name], errors="coerce")
    open_present = frame["open"].notna()
    if (open_present & frame["open"].le(0)).any():
        raise XSMOMDevelopmentEvidenceError("EXECUTION_OPEN_MUST_BE_POSITIVE_WHEN_PRESENT")
    if (
        not frame.loc[open_present, "open_observed_at_utc"]
        .eq(frame.loc[open_present, "timestamp"])
        .all()
    ):
        raise XSMOMDevelopmentEvidenceError("EXECUTION_OPEN_IS_NOT_BOUND_TO_EXACT_BAR_OPEN")
    if frame.loc[~open_present, "open_observed_at_utc"].notna().any():
        raise XSMOMDevelopmentEvidenceError("MISSING_OPEN_CANNOT_HAVE_AN_OBSERVATION_TIME")
    closed_by_cutoff = frame["bar_closed_at_utc"] <= manifest.evidence_end
    if (
        frame.loc[closed_by_cutoff, "mark_price"].isna().any()
        or (frame.loc[closed_by_cutoff, "mark_price"] <= 0).any()
    ):
        raise XSMOMDevelopmentEvidenceError("CLOSED_EXECUTION_BAR_REQUIRES_A_POSITIVE_MARK")
    if (
        not frame.loc[closed_by_cutoff, "mark_observed_at_utc"]
        .eq(frame.loc[closed_by_cutoff, "bar_closed_at_utc"])
        .all()
    ):
        raise XSMOMDevelopmentEvidenceError("EXECUTION_MARK_IS_NOT_AVAILABLE_AT_BAR_CLOSE")
    future_close = ~closed_by_cutoff
    if (
        frame.loc[future_close, "mark_price"].notna().any()
        or frame.loc[future_close, "mark_observed_at_utc"].notna().any()
    ):
        raise XSMOMDevelopmentEvidenceError("ARTIFACT_REVEALS_A_POST_CUTOFF_CLOSE_OR_MARK")
    event = frame["market_event"].ne("NONE")
    if (
        frame.loc[event, "market_event_observed_at_utc"].isna().any()
        or (frame.loc[event, "market_event_observed_at_utc"] > frame.loc[event, "timestamp"]).any()
    ):
        raise XSMOMDevelopmentEvidenceError("MARKET_EVENT_WAS_NOT_KNOWN_BY_EFFECTIVE_TIME")
    if frame.loc[~event, "market_event_observed_at_utc"].notna().any():
        raise XSMOMDevelopmentEvidenceError("NONE_MARKET_EVENT_CANNOT_HAVE_OBSERVATION_TIME")
    return frame.sort_values(["timestamp", "instrument_id"]).reset_index(drop=True)


def _normalise_execution_terms(
    rows: list[dict[str, Any]], manifest: XSMOMDevelopmentManifest
) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    _require_columns(frame, EXECUTION_TERM_COLUMNS, "EXECUTION_TERMS")
    for name in (
        "execution_timestamp_utc",
        "observed_at_utc",
        "fee_observed_at_utc",
        "valid_from_utc",
        "cost_sample_end_utc",
    ):
        frame[name] = pd.to_datetime(frame[name], utc=True, errors="coerce")
        if frame[name].isna().any():
            raise XSMOMDevelopmentEvidenceError(f"TERMS_{name.upper()}_IS_INVALID")
    raw_valid_to = frame["valid_to_utc"].copy()
    frame["valid_to_utc"] = pd.to_datetime(raw_valid_to, utc=True, errors="coerce")
    if (raw_valid_to.notna() & frame["valid_to_utc"].isna()).any():
        raise XSMOMDevelopmentEvidenceError("TERMS_VALID_TO_IS_INVALID")
    if frame.duplicated(["execution_timestamp_utc", "instrument_id"]).any():
        raise XSMOMDevelopmentEvidenceError("EXECUTION_TERMS_HAVE_DUPLICATE_TIMESTAMP_ID")
    if not frame["venue"].eq(VENUE).all() or not frame["market"].eq(MARKET).all():
        raise XSMOMDevelopmentEvidenceError("EXECUTION_TERMS_ARE_NOT_BINANCE_SPOT_ONLY")
    if (frame["execution_timestamp_utc"] > manifest.evidence_end).any():
        raise XSMOMDevelopmentEvidenceError("EXECUTION_TERMS_REACH_BEYOND_EVIDENCE_CUTOFF")
    for row in frame.itertuples(index=False):
        if isinstance(row.cmc_id, bool) or not isinstance(row.cmc_id, int) or row.cmc_id < 1:
            raise XSMOMDevelopmentEvidenceError("TERMS_CMC_ID_MUST_BE_POSITIVE_INTEGER")
        if row.instrument_id != f"CMC:{row.cmc_id}":
            raise XSMOMDevelopmentEvidenceError("TERMS_INSTRUMENT_ID_IS_NOT_STABLE_CMC_ID")
        if (
            not isinstance(row.venue_symbol, str)
            or _VENUE_SYMBOL_RE.fullmatch(row.venue_symbol) is None
        ):
            raise XSMOMDevelopmentEvidenceError("TERMS_VENUE_SYMBOL_IS_INVALID")
    numeric_positive = (
        "tick_size",
        "quantity_step",
        "min_quantity",
        "max_quantity",
        "min_notional_quote_usdt",
    )
    numeric_nonnegative = (
        "taker_fee_bps",
        "spread_cost_bps_p75",
        "impact_cost_bps_p75",
    )
    for name in (*numeric_positive, *numeric_nonnegative, "max_notional_quote_usdt"):
        frame[name] = pd.to_numeric(frame[name], errors="coerce")
    for name in numeric_positive:
        if (
            frame[name].isna().any()
            or (frame[name] <= 0).any()
            or not frame[name].map(math.isfinite).all()
        ):
            raise XSMOMDevelopmentEvidenceError(f"TERMS_{name.upper()}_MUST_BE_POSITIVE")
    for name in numeric_nonnegative:
        if (
            frame[name].isna().any()
            or (frame[name] < 0).any()
            or not frame[name].map(math.isfinite).all()
        ):
            raise XSMOMDevelopmentEvidenceError(f"TERMS_{name.upper()}_MUST_BE_NONNEGATIVE")
    max_notional_present = frame["max_notional_quote_usdt"].notna()
    if (frame.loc[max_notional_present, "max_notional_quote_usdt"] <= 0).any():
        raise XSMOMDevelopmentEvidenceError("TERMS_MAX_NOTIONAL_MUST_BE_POSITIVE_OR_NULL")
    if (frame["max_quantity"] < frame["min_quantity"]).any():
        raise XSMOMDevelopmentEvidenceError("TERMS_MAX_QUANTITY_IS_BELOW_MIN_QUANTITY")
    if (
        max_notional_present & (frame["max_notional_quote_usdt"] < frame["min_notional_quote_usdt"])
    ).any():
        raise XSMOMDevelopmentEvidenceError("TERMS_MAX_NOTIONAL_IS_BELOW_MIN_NOTIONAL")
    decision = frame["execution_timestamp_utc"] - pd.Timedelta(days=1)
    if not frame["execution_timestamp_utc"].dt.dayofweek.eq(4).all():
        raise XSMOMDevelopmentEvidenceError("TERMS_EXECUTION_MUST_BE_EXACT_FRIDAY")
    if (
        (frame["observed_at_utc"] > decision).any()
        or (frame["fee_observed_at_utc"] > decision).any()
        or (frame["cost_sample_end_utc"] > decision).any()
    ):
        raise XSMOMDevelopmentEvidenceError("TERMS_OR_COSTS_WERE_NOT_KNOWN_BY_THURSDAY")
    active = (frame["valid_from_utc"] <= frame["execution_timestamp_utc"]) & (
        frame["valid_to_utc"].isna() | (frame["execution_timestamp_utc"] < frame["valid_to_utc"])
    )
    if not active.all():
        raise XSMOMDevelopmentEvidenceError("SYMBOL_RULES_ARE_NOT_ACTIVE_AT_EXECUTION")
    for name in ("rules_source_sha256", "fee_source_sha256", "cost_source_sha256"):
        for value in frame[name]:
            _sha(name, value)
    if (
        not frame["fee_source_sha256"]
        .eq(manifest.source_artifact_sha256["binance_account_fees"])
        .all()
    ):
        raise XSMOMDevelopmentEvidenceError("FEE_ROWS_DO_NOT_BIND_MANIFEST_ACCOUNT_FEE_ARTIFACT")
    if (
        not frame["cost_source_sha256"]
        .eq(manifest.source_artifact_sha256["symbol_cost_model"])
        .all()
    ):
        raise XSMOMDevelopmentEvidenceError("COST_ROWS_DO_NOT_BIND_MANIFEST_COST_ARTIFACT")
    return frame.sort_values(["execution_timestamp_utc", "instrument_id"]).reset_index(drop=True)


def _verify_symbol_rule_ledger(
    terms: pd.DataFrame,
    manifest: XSMOMDevelopmentManifest,
    ledger: BinanceSpotSymbolRulesLedger | None,
) -> None:
    """Bind denormalized execution rows to the canonical PIT rules ledger."""

    if ledger is None:
        raise XSMOMDevelopmentEvidenceError("REAL_ARTIFACT_REQUIRES_SYMBOL_RULE_LEDGER")
    if ledger.digest() != manifest.source_artifact_sha256["binance_symbol_rules"]:
        raise XSMOMDevelopmentEvidenceError("SYMBOL_RULE_LEDGER_DIGEST_MISMATCH")
    # The current ledger intentionally cannot create AVAILABLE_REAL: local
    # hashes do not constitute independent external attestation. Keep the
    # detailed lookup code below future-compatible, but stop before pretending
    # any schema-v2 row is an authenticated execution rule.
    if ledger.attestation_status != "AVAILABLE_REAL":
        raise XSMOMDevelopmentEvidenceError(
            "SYMBOL_RULE_LEDGER_LACKS_INDEPENDENT_EXTERNAL_ATTESTATION"
        )
    for row in terms.itertuples(index=False):
        decision = row.execution_timestamp_utc - pd.Timedelta(days=1)
        as_of = decision.isoformat().replace("+00:00", "Z")
        lookup = ledger.lookup(
            str(row.venue_symbol),
            as_of_utc=as_of,
            max_age=MAX_SYMBOL_RULE_AGE,
        )
        if lookup.availability is not SymbolRuleAvailability.AVAILABLE_REAL:
            raise XSMOMDevelopmentEvidenceError(
                f"SYMBOL_RULE_UNAVAILABLE_{row.venue_symbol}_{lookup.availability.value}"
            )
        rule = lookup.rule
        if rule is None:
            raise XSMOMDevelopmentEvidenceError("AVAILABLE_SYMBOL_RULE_HAS_NO_RULE")
        expected = {
            "tick_size": rule.tick_size,
            "quantity_step": rule.market_quantity_step,
            "min_quantity": rule.market_min_quantity,
            "max_quantity": rule.market_max_quantity,
        }
        min_notionals = [
            value
            for value, applies in (
                (rule.min_notional_quote, rule.min_notional_apply_to_market),
                (rule.notional_min_quote, rule.notional_apply_min_to_market),
            )
            if value is not None and bool(applies)
        ]
        if not min_notionals:
            raise XSMOMDevelopmentEvidenceError(
                f"NO_MARKET_APPLICABLE_MIN_NOTIONAL_FOR_{row.venue_symbol}"
            )
        expected["min_notional_quote_usdt"] = max(min_notionals, key=Decimal)
        if rule.notional_apply_max_to_market:
            maximum = rule.notional_max_quote
            if maximum is None:
                raise XSMOMDevelopmentEvidenceError(
                    f"MARKET_APPLICABLE_MAX_NOTIONAL_IS_MISSING_FOR_{row.venue_symbol}"
                )
            expected["max_notional_quote_usdt"] = maximum
        if any(
            value is None or Decimal(str(getattr(row, name))) != Decimal(value)
            for name, value in expected.items()
        ):
            raise XSMOMDevelopmentEvidenceError(
                f"DENORMALIZED_SYMBOL_RULE_DIVERGES_FOR_{row.venue_symbol}"
            )
        if (
            row.observed_at_utc.isoformat().replace("+00:00", "Z")
            != lookup.snapshot_observed_at_utc
            or row.rules_source_sha256 != rule.source_receipt_sha256
        ):
            raise XSMOMDevelopmentEvidenceError(
                f"SYMBOL_RULE_PROVENANCE_DIVERGES_FOR_{row.venue_symbol}"
            )


def _build_decisions(
    selection: pd.DataFrame,
    manifest: XSMOMDevelopmentManifest,
    spec: XSMOMSpec,
) -> list[XSMOMDecision]:
    decisions: list[XSMOMDecision] = []
    for timestamp in pd.date_range(
        manifest.decision_start, manifest.decision_end, freq="7D", tz="UTC"
    ):
        prefix = selection[selection["bar_closed_at_utc"] <= timestamp].copy()
        decision = build_xsmom_decision(prefix, spec, timestamp)
        if decision.status != "TARGETS_CREATED_RESEARCH_ONLY":
            raise XSMOMDevelopmentEvidenceError(
                f"DECISION_{timestamp.date().isoformat()}_{decision.reason}"
            )
        if decision.exact_execution_timestamp != timestamp + pd.Timedelta(days=1):
            raise XSMOMDevelopmentEvidenceError("DECISION_DOES_NOT_EXECUTE_AT_EXACT_FRIDAY_OPEN")
        if len(decision.candidate_targets) != 20 or len(decision.liquidity_control_targets) != 20:
            raise XSMOMDevelopmentEvidenceError("DECISION_DOES_NOT_HAVE_EXACT_PAIRED_TOP20")
        candidate_cohorts = {target.cohort_digest for target in decision.candidate_targets}
        control_cohorts = {target.cohort_digest for target in decision.liquidity_control_targets}
        if candidate_cohorts != control_cohorts or candidate_cohorts != {decision.cohort_digest}:
            raise XSMOMDevelopmentEvidenceError("CANDIDATE_AND_CONTROL_COHORTS_DIVERGE")
        decisions.append(decision)
    if len(decisions) < 4:
        raise XSMOMDevelopmentEvidenceError("FEWER_THAN_FOUR_COMPLETE_WEEKLY_WINDOWS")
    return decisions


@dataclass
class _PortfolioState:
    name: str
    cash: float = INITIAL_CAPITAL_QUOTE_USDT
    quantity: dict[str, float] = field(default_factory=dict)
    last_mark: dict[str, float] = field(default_factory=dict)
    history: list[float] = field(default_factory=lambda: [INITIAL_CAPITAL_QUOTE_USDT])
    weekly_boundaries: list[float] = field(default_factory=list)
    total_cost: float = 0.0
    executions: list[XSMOMDevelopmentExecution] = field(default_factory=list)


def _floor_step(value: float, step: float) -> float:
    return math.floor((value + 1e-12) / step) * step


def _round_price(value: float, tick: float, side: str) -> float:
    units = value / tick
    rounded = math.ceil(units - 1e-12) if side == "buy" else math.floor(units + 1e-12)
    return rounded * tick


def _row_open(row: Any | None) -> float | None:
    if row is None or row.data_status != "VALID":
        return None
    try:
        value = float(row.open)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value > 0 else None


def _portfolio_value(
    state: _PortfolioState,
    timestamp: pd.Timestamp,
    bars: Mapping[tuple[pd.Timestamp, str], Any],
    *,
    use_exact_open: bool,
) -> float:
    value = state.cash
    for instrument_id, quantity in state.quantity.items():
        row = bars.get((timestamp, instrument_id))
        price = _row_open(row) if use_exact_open else state.last_mark.get(instrument_id)
        if price is None:
            # At an execution boundary the exact open is already observable,
            # while that bar's closing mark is not.  This fallback never reads
            # a close from the future.
            price = _row_open(row)
        if price is None:
            raise XSMOMDevelopmentEvidenceError(
                f"POSITION_{instrument_id}_HAS_NO_CAUSAL_MARK_AT_{timestamp.isoformat()}"
            )
        value += quantity * price
    if not math.isfinite(value) or value <= 0:
        raise XSMOMDevelopmentEvidenceError("PORTFOLIO_EQUITY_IS_NOT_FINITE_AND_POSITIVE")
    return value


def _term_map(terms: pd.DataFrame) -> dict[tuple[pd.Timestamp, str], Any]:
    return {
        (row.execution_timestamp_utc, str(row.instrument_id)): row
        for row in terms.itertuples(index=False)
    }


def _record_refusal(
    state: _PortfolioState,
    decision: pd.Timestamp,
    execution: pd.Timestamp,
    instrument_id: str,
    venue_symbol: str,
    side: str,
    requested_quantity: float,
    reason: str,
    *,
    status: str = "EXPIRED",
) -> None:
    state.executions.append(
        XSMOMDevelopmentExecution(
            portfolio=state.name,
            decision_timestamp=decision.isoformat(),
            execution_timestamp=execution.isoformat(),
            instrument_id=instrument_id,
            venue_symbol=venue_symbol,
            side=side,
            requested_quantity=requested_quantity,
            filled_quantity=0.0,
            refused_quantity=requested_quantity,
            open_price=None,
            fill_price=None,
            fee_quote_usdt=0.0,
            adverse_price_cost_quote_usdt=0.0,
            status=status,
            reason=reason,
        )
    )


def _rebalance(
    state: _PortfolioState,
    decision_timestamp: pd.Timestamp,
    execution_timestamp: pd.Timestamp,
    targets: Mapping[str, tuple[str, float]],
    bars: Mapping[tuple[pd.Timestamp, str], Any],
    terms: Mapping[tuple[pd.Timestamp, str], Any],
    *,
    cost_multiplier: float,
    fill_fraction: float,
    blocked_buys: set[str],
) -> None:
    equity = _portfolio_value(state, execution_timestamp, bars, use_exact_open=True)
    desired = {instrument_id: 0.0 for instrument_id in state.quantity}
    desired.update({instrument_id: weight for instrument_id, (_, weight) in targets.items()})
    requests: list[tuple[bool, str, str, float, float]] = []
    for instrument_id in sorted(desired):
        row = bars.get((execution_timestamp, instrument_id))
        venue_symbol = (
            targets[instrument_id][0]
            if instrument_id in targets
            else str(row.venue_symbol)
            if row is not None
            else "UNKNOWN"
        )
        current_price = _row_open(row) or state.last_mark.get(instrument_id)
        if current_price is None and state.quantity.get(instrument_id, 0.0) > 1e-12:
            raise XSMOMDevelopmentEvidenceError(
                f"NO_CAUSAL_SIZING_PRICE_FOR_{instrument_id}_{execution_timestamp.date()}"
            )
        current_value = state.quantity.get(instrument_id, 0.0) * (current_price or 0.0)
        delta = desired[instrument_id] * equity - current_value
        if abs(delta) <= 1e-10:
            continue
        requests.append((delta > 0, instrument_id, venue_symbol, delta, current_price or 0.0))
    requests.sort(key=lambda item: (item[0], item[1]))  # sells before buys

    for is_buy, instrument_id, venue_symbol, delta, sizing_price in requests:
        side = "buy" if is_buy else "sell"
        row = bars.get((execution_timestamp, instrument_id))
        open_price = _row_open(row)
        requested_quantity = abs(delta) / sizing_price if sizing_price > 0 else 0.0
        if row is None or open_price is None or not bool(row.tradable):
            _record_refusal(
                state,
                decision_timestamp,
                execution_timestamp,
                instrument_id,
                venue_symbol,
                side,
                requested_quantity,
                "MISSING_OR_NONTRADABLE_EXACT_FRIDAY_OPEN_NO_RETRY",
            )
            continue
        if is_buy and instrument_id in blocked_buys:
            _record_refusal(
                state,
                decision_timestamp,
                execution_timestamp,
                instrument_id,
                venue_symbol,
                side,
                requested_quantity,
                "NEW_BUY_BLOCKED_BY_CAUSAL_DELISTING_EVENT",
                status="REFUSED",
            )
            continue
        term = terms.get((execution_timestamp, instrument_id))
        if term is None:
            raise XSMOMDevelopmentEvidenceError(
                f"MISSING_SYMBOL_SPECIFIC_TERMS_FOR_{instrument_id}_{execution_timestamp.date()}"
            )
        if (
            str(term.venue_symbol) != str(row.venue_symbol)
            or str(term.venue_symbol) != venue_symbol
        ):
            raise XSMOMDevelopmentEvidenceError(
                f"SYMBOL_BINDING_DIVERGES_AT_EXECUTION_FOR_{instrument_id}"
            )
        executable_quantity = requested_quantity * fill_fraction
        executable_quantity = min(executable_quantity, float(term.max_quantity))
        executable_quantity = _floor_step(executable_quantity, float(term.quantity_step))
        if not is_buy:
            executable_quantity = min(executable_quantity, state.quantity.get(instrument_id, 0.0))
            executable_quantity = _floor_step(executable_quantity, float(term.quantity_step))
        adverse_bps = cost_multiplier * (
            float(term.spread_cost_bps_p75) + float(term.impact_cost_bps_p75)
        )
        raw_fill_price = open_price * (
            1.0 + adverse_bps / 10_000.0 if is_buy else 1.0 - adverse_bps / 10_000.0
        )
        fill_price = _round_price(raw_fill_price, float(term.tick_size), side)
        if fill_price <= 0:
            raise XSMOMDevelopmentEvidenceError("ADVERSE_COST_MODEL_PRODUCED_NONPOSITIVE_PRICE")
        max_notional = (
            float(term.max_notional_quote_usdt) if pd.notna(term.max_notional_quote_usdt) else None
        )
        if max_notional is not None and executable_quantity * fill_price > max_notional:
            executable_quantity = _floor_step(max_notional / fill_price, float(term.quantity_step))
        notional = executable_quantity * fill_price
        if (
            executable_quantity < float(term.min_quantity)
            or notional < float(term.min_notional_quote_usdt)
            or executable_quantity <= 1e-12
        ):
            _record_refusal(
                state,
                decision_timestamp,
                execution_timestamp,
                instrument_id,
                venue_symbol,
                side,
                requested_quantity,
                "ROUNDED_QUANTITY_FAILS_POINT_IN_TIME_SYMBOL_FILTERS",
                status="REFUSED",
            )
            continue
        fee_rate = float(term.taker_fee_bps) * cost_multiplier / 10_000.0
        if is_buy and notional * (1.0 + fee_rate) > state.cash:
            executable_quantity = _floor_step(
                state.cash / (fill_price * (1.0 + fee_rate)),
                float(term.quantity_step),
            )
            notional = executable_quantity * fill_price
        if (
            executable_quantity < float(term.min_quantity)
            or notional < float(term.min_notional_quote_usdt)
            or executable_quantity <= 1e-12
        ):
            _record_refusal(
                state,
                decision_timestamp,
                execution_timestamp,
                instrument_id,
                venue_symbol,
                side,
                requested_quantity,
                "AVAILABLE_CASH_FAILS_POINT_IN_TIME_SYMBOL_FILTERS",
                status="REFUSED",
            )
            continue
        fee = notional * fee_rate
        signed_quantity = executable_quantity if is_buy else -executable_quantity
        state.cash -= signed_quantity * fill_price + fee
        state.quantity[instrument_id] = state.quantity.get(instrument_id, 0.0) + signed_quantity
        if abs(state.quantity[instrument_id]) <= 1e-12:
            state.quantity.pop(instrument_id, None)
        adverse_cost = abs(fill_price - open_price) * executable_quantity
        state.total_cost += fee + adverse_cost
        refused_quantity = max(0.0, requested_quantity - executable_quantity)
        if refused_quantity <= 1e-9:
            refused_quantity = 0.0
            status = "FILLED"
        else:
            status = "PARTIALLY_FILLED_EXPIRED"
        state.executions.append(
            XSMOMDevelopmentExecution(
                portfolio=state.name,
                decision_timestamp=decision_timestamp.isoformat(),
                execution_timestamp=execution_timestamp.isoformat(),
                instrument_id=instrument_id,
                venue_symbol=venue_symbol,
                side=side,
                requested_quantity=requested_quantity,
                filled_quantity=executable_quantity,
                refused_quantity=refused_quantity,
                open_price=open_price,
                fill_price=fill_price,
                fee_quote_usdt=fee,
                adverse_price_cost_quote_usdt=adverse_cost,
                status=status,
                reason=("UNFILLED_REMAINDER_EXPIRED_NO_RETRY" if refused_quantity > 1e-9 else ""),
            )
        )


def _performance(state: _PortfolioState) -> XSMOMDevelopmentPerformance:
    weekly = state.weekly_boundaries
    if len(weekly) < 2:
        raise XSMOMDevelopmentEvidenceError("PORTFOLIO_HAS_NO_COMPLETE_WEEKLY_RETURN")
    returns = [right / left - 1.0 for left, right in zip(weekly, weekly[1:], strict=False)]
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / len(returns)
    volatility = math.sqrt(variance)
    peak = state.history[0]
    max_drawdown = 0.0
    for value in state.history:
        peak = max(peak, value)
        max_drawdown = min(max_drawdown, value / peak - 1.0)
    executions = state.executions
    return XSMOMDevelopmentPerformance(
        initial_equity_quote_usdt=INITIAL_CAPITAL_QUOTE_USDT,
        terminal_equity_quote_usdt=weekly[-1],
        total_return=weekly[-1] / INITIAL_CAPITAL_QUOTE_USDT - 1.0,
        annualized_weekly_sharpe=mean / volatility * math.sqrt(52.0) if volatility > 0 else 0.0,
        max_drawdown=max_drawdown,
        total_cost_quote_usdt=state.total_cost,
        execution_count=len(executions),
        filled_count=sum(item.status == "FILLED" for item in executions),
        partial_count=sum(item.status == "PARTIALLY_FILLED_EXPIRED" for item in executions),
        refused_or_expired_count=sum(item.status in {"REFUSED", "EXPIRED"} for item in executions),
        same_boundary_fill_count=sum(
            item.side != "terminal_write_down"
            and item.filled_quantity > 0
            and item.decision_timestamp == item.execution_timestamp
            for item in executions
        ),
    )


def _block_counts(
    candidate: Sequence[float], benchmarks: Mapping[str, Sequence[float]]
) -> dict[str, int]:
    interval_count = len(candidate) - 1
    if interval_count < 4 or any(len(values) != len(candidate) for values in benchmarks.values()):
        raise XSMOMDevelopmentEvidenceError("FOUR_BLOCK_CURVES_DO_NOT_ALIGN")
    interval_indexes = list(range(1, len(candidate)))
    base, remainder = divmod(len(interval_indexes), 4)
    blocks: list[list[int]] = []
    cursor = 0
    for index in range(4):
        size = base + int(index < remainder)
        blocks.append(interval_indexes[cursor : cursor + size])
        cursor += size
    counts = {name: 0 for name in benchmarks}
    for block in blocks:
        start = block[0] - 1
        end = block[-1]
        candidate_return = candidate[end] / candidate[start] - 1.0
        for name, values in benchmarks.items():
            benchmark_return = values[end] / values[start] - 1.0
            counts[name] += int(candidate_return > benchmark_return)
    return counts


def _scenario(
    decisions: Sequence[XSMOMDecision],
    bars_frame: pd.DataFrame,
    terms_frame: pd.DataFrame,
    *,
    cost_multiplier: float,
    fill_fraction: float,
) -> XSMOMDevelopmentScenario:
    bars = {
        (row.timestamp, str(row.instrument_id)): row for row in bars_frame.itertuples(index=False)
    }
    terms = _term_map(terms_frame)
    states = {
        name: _PortfolioState(name=name)
        for name in ("candidate_xsmom", "liquidity_control", "btc_95_cash_5", "btc_100")
    }
    decisions_by_execution = {
        decision.exact_execution_timestamp: decision for decision in decisions
    }
    first_execution = decisions[0].exact_execution_timestamp
    terminal = decisions[-1].exact_execution_timestamp + pd.Timedelta(days=7)
    close_rows: dict[pd.Timestamp, list[Any]] = {}
    event_rows: dict[pd.Timestamp, list[Any]] = {}
    for row in bars_frame.itertuples(index=False):
        if row.bar_closed_at_utc <= terminal and pd.notna(row.mark_price):
            close_rows.setdefault(row.bar_closed_at_utc, []).append(row)
        if row.market_event != "NONE" and row.timestamp <= terminal:
            event_rows.setdefault(row.timestamp, []).append(row)
    event_times = sorted(
        set(close_rows) | set(event_rows) | set(decisions_by_execution) | {terminal}
    )
    blocked_buys: set[str] = set()
    btc_targets = {"CMC:1": ("BTCUSDT", 0.95)}
    btc_full_targets = {"CMC:1": ("BTCUSDT", 1.0)}

    for timestamp in event_times:
        for row in close_rows.get(timestamp, []):
            value = float(row.mark_price)
            for state in states.values():
                state.last_mark[str(row.instrument_id)] = value
        for row in event_rows.get(timestamp, []):
            instrument_id = str(row.instrument_id)
            if row.market_event in {"DELISTING_ANNOUNCED", "DELISTING_CONFIRMED"}:
                blocked_buys.add(instrument_id)
            if row.market_event == "DELISTING_CONFIRMED":
                for state in states.values():
                    quantity = state.quantity.pop(instrument_id, 0.0)
                    if quantity <= 0:
                        continue
                    state.executions.append(
                        XSMOMDevelopmentExecution(
                            portfolio=state.name,
                            decision_timestamp=timestamp.isoformat(),
                            execution_timestamp=timestamp.isoformat(),
                            instrument_id=instrument_id,
                            venue_symbol=str(row.venue_symbol),
                            side="terminal_write_down",
                            requested_quantity=quantity,
                            filled_quantity=quantity,
                            refused_quantity=0.0,
                            open_price=None,
                            fill_price=0.0,
                            fee_quote_usdt=0.0,
                            adverse_price_cost_quote_usdt=quantity
                            * state.last_mark.get(instrument_id, 0.0),
                            status="WRITE_DOWN_ZERO",
                            reason="CONFIRMED_DELISTING_WITHOUT_DEMONSTRATED_EXECUTABLE_EXIT",
                        )
                    )
        decision = decisions_by_execution.get(timestamp)
        if decision is not None:
            for state in states.values():
                state.weekly_boundaries.append(
                    _portfolio_value(state, timestamp, bars, use_exact_open=True)
                )
            candidate_targets = {
                target.instrument_id: (target.venue_symbol, target.target_weight)
                for target in decision.candidate_targets
            }
            control_targets = {
                target.instrument_id: (target.venue_symbol, target.target_weight)
                for target in decision.liquidity_control_targets
            }
            _rebalance(
                states["candidate_xsmom"],
                decision.decision_timestamp,
                timestamp,
                candidate_targets,
                bars,
                terms,
                cost_multiplier=cost_multiplier,
                fill_fraction=fill_fraction,
                blocked_buys=blocked_buys,
            )
            _rebalance(
                states["liquidity_control"],
                decision.decision_timestamp,
                timestamp,
                control_targets,
                bars,
                terms,
                cost_multiplier=cost_multiplier,
                fill_fraction=fill_fraction,
                blocked_buys=blocked_buys,
            )
            if timestamp == first_execution:
                _rebalance(
                    states["btc_95_cash_5"],
                    decision.decision_timestamp,
                    timestamp,
                    btc_targets,
                    bars,
                    terms,
                    cost_multiplier=cost_multiplier,
                    fill_fraction=fill_fraction,
                    blocked_buys=blocked_buys,
                )
                _rebalance(
                    states["btc_100"],
                    decision.decision_timestamp,
                    timestamp,
                    btc_full_targets,
                    bars,
                    terms,
                    cost_multiplier=cost_multiplier,
                    fill_fraction=fill_fraction,
                    blocked_buys=blocked_buys,
                )
        if timestamp >= first_execution:
            for state in states.values():
                state.history.append(_portfolio_value(state, timestamp, bars, use_exact_open=False))

    for state in states.values():
        state.weekly_boundaries.append(_portfolio_value(state, terminal, bars, use_exact_open=True))
    candidate = states["candidate_xsmom"].weekly_boundaries
    benchmarks = {
        name: state.weekly_boundaries for name, state in states.items() if name != "candidate_xsmom"
    }
    executions = tuple(
        sorted(
            (item for state in states.values() for item in state.executions),
            key=lambda item: (
                item.execution_timestamp,
                item.portfolio,
                item.instrument_id,
                item.side,
            ),
        )
    )
    return XSMOMDevelopmentScenario(
        cost_multiplier=cost_multiplier,
        fill_fraction=fill_fraction,
        performance={name: _performance(state) for name, state in states.items()},
        block_outperformance_counts=_block_counts(candidate, benchmarks),
        executions=executions,
    )


def _current_real_activation_blockers(spec: XSMOMSpec) -> tuple[str, ...]:
    blockers: list[str] = []
    if not bool(spec.evidence_policy["development_or_holdout_window_activated"]):
        blockers.append("SEALED_SPEC_DEVELOPMENT_WINDOW_NOT_ACTIVATED")
    if not bool(spec.evidence_policy["economic_evaluation_allowed"]):
        blockers.append("SEALED_SPEC_ECONOMIC_EVALUATION_FORBIDDEN")
    if not bool(spec.evidence_policy["independent_preregistration_timestamp_exists"]):
        blockers.append("SEALED_SPEC_LACKS_INDEPENDENT_PREREGISTRATION_TIMESTAMP")
    if spec.promotion_blockers["stablecoin_point_in_time_evidence"].startswith("UNKNOWN"):
        blockers.append("SEALED_SPEC_STABLECOIN_POINT_IN_TIME_EVIDENCE_UNKNOWN")
    if spec.promotion_blockers["costs"] != "ACCOUNT_AND_SYMBOL_SPECIFIC_COSTS_NOT_BOUND":
        blockers.append("SEALED_SPEC_COST_BLOCKER_WAS_UNEXPECTEDLY_REWRITTEN")
    else:
        blockers.append("SEALED_SPEC_ACCOUNT_AND_SYMBOL_COSTS_NOT_BOUND")
    if (
        spec.promotion_blockers["minimum_notional"]
        == "POINT_IN_TIME_SYMBOL_RULES_DATASET_NOT_BUILT"
    ):
        blockers.append("SEALED_SPEC_POINT_IN_TIME_SYMBOL_RULES_NOT_BUILT")
    # Binance's quote filters are denominated in USDT, not USD. The current
    # declaration and panel have no causal conversion contract, so even a
    # future otherwise-complete real bundle must remain insufficient here.
    blockers.append("POINT_IN_TIME_USDT_USD_CONVERSION_NOT_IMPLEMENTED")
    return tuple(blockers)


def evaluate_xsmom_development(
    artifact_directory: str | Path,
    spec: XSMOMSpec,
    *,
    allow_synthetic_test_artifact: bool = False,
    symbol_rules_ledger: BinanceSpotSymbolRulesLedger | None = None,
) -> XSMOMDevelopmentVerdict:
    """Evaluate one verified bundle without ever returning a promotional verdict.

    ``allow_synthetic_test_artifact`` exists solely for deterministic offline
    contract tests.  It does not make synthetic performance economic evidence.
    Real artifacts remain blocked until a future independently timestamped
    declaration explicitly activates a development window.
    """

    hashes: dict[str, str] = {}
    try:
        validated_spec = XSMOMSpec(**spec.canonical_payload())
        if validated_spec.seal() != SPEC_SEAL or spec.seal() != SPEC_SEAL:
            raise XSMOMDevelopmentEvidenceError("SPEC_RECONSTRUCTION_OR_SEAL_MISMATCH")
        hashes["spec"] = spec.seal()
        root = Path(artifact_directory)
        manifest, manifest_bytes = _read_manifest(root)
        hashes["manifest.json"] = sha256_of_bytes(manifest_bytes)
    except (AttributeError, TypeError, ValueError) as exc:
        return _insufficient(spec, hashes, str(exc) or type(exc).__name__.upper())

    if manifest.artifact_kind == REAL_ARTIFACT_KIND:
        blockers = _current_real_activation_blockers(spec)
        if blockers:
            return _insufficient(spec, hashes, *blockers)
    elif not allow_synthetic_test_artifact:
        return _insufficient(spec, hashes, "SYNTHETIC_ARTIFACT_REQUIRES_EXPLICIT_TEST_MODE")

    try:
        loaded: dict[str, list[dict[str, Any]]] = {}
        for filename in ARTIFACT_FILES:
            rows, payload = _read_artifact_file(
                root,
                filename,
                manifest.file_sha256[filename],
                manifest.row_counts[filename],
            )
            loaded[filename] = rows
            hashes[filename] = sha256_of_bytes(payload)
        hashes["dataset"] = sha256_of_text(canonical_dumps(dict(sorted(hashes.items()))))
        selection = _normalise_selection(loaded["selection_panel.jsonl"], manifest)
        bars = _normalise_execution_bars(loaded["execution_bars.jsonl"], manifest)
        terms = _normalise_execution_terms(loaded["execution_terms.jsonl"], manifest)
        if manifest.artifact_kind == REAL_ARTIFACT_KIND:
            _verify_symbol_rule_ledger(terms, manifest, symbol_rules_ledger)
        decisions = _build_decisions(selection, manifest, spec)
        normal = _scenario(
            decisions,
            bars,
            terms,
            cost_multiplier=1.0,
            fill_fraction=1.0,
        )
        stress = _scenario(
            decisions,
            bars,
            terms,
            cost_multiplier=2.0,
            fill_fraction=0.5,
        )
    except (KeyError, TypeError, ValueError) as exc:
        return _insufficient(spec, hashes, str(exc) or type(exc).__name__.upper())

    scenarios = {"normal": normal, "stress_2x_costs_50pct_fills": stress}
    reasons: list[str] = []
    candidate = normal.performance["candidate_xsmom"]
    if candidate.total_return <= 0:
        reasons.append("NORMAL_CANDIDATE_NET_RETURN_IS_NOT_POSITIVE")
    for benchmark in ("liquidity_control", "btc_95_cash_5", "btc_100"):
        if candidate.total_return <= normal.performance[benchmark].total_return:
            reasons.append(f"NORMAL_CANDIDATE_DOES_NOT_OUTPERFORM_{benchmark.upper()}")
    if candidate.max_drawdown < -0.25:
        reasons.append("NORMAL_CANDIDATE_DRAWDOWN_EXCEEDS_25_PERCENT")
    if stress.performance["candidate_xsmom"].total_return < 0:
        reasons.append("STRESS_2X_COSTS_50PCT_FILLS_RETURN_IS_NEGATIVE")
    if any(
        snapshot.same_boundary_fill_count
        for scenario in scenarios.values()
        for snapshot in scenario.performance.values()
    ):
        reasons.append("SAME_BOUNDARY_FILL_DETECTED")
    status: VerdictStatus = "NO_GO" if reasons else "INSUFFICIENT_EVIDENCE"
    if not reasons:
        reasons.append("DEVELOPMENT_RULE_NOT_FALSIFIED_BY_SYNTHETIC_CONTRACT_FIXTURE")
    if manifest.artifact_kind == SYNTHETIC_ARTIFACT_KIND:
        reasons.append("SYNTHETIC_TEST_DATA_IS_NOT_ECONOMIC_EVIDENCE")
    reasons.extend(
        (
            "PBO_NOT_IDENTIFIABLE_FOR_SINGLE_TRIAL",
            "FOUR_BLOCK_COUNTS_ARE_DESCRIPTIVE_NOT_AN_INDEPENDENT_PROMOTION_TEST",
            "DEVELOPMENT_ONLY_CANNOT_AUTHORIZE_PROMOTION_OR_REAL_MONEY",
        )
    )
    return XSMOMDevelopmentVerdict(
        status=status,
        strategy_id=spec.strategy_id,
        evidence_hashes=hashes,
        decision_count=len(decisions),
        completed_weekly_periods=len(decisions),
        cohort_digests=tuple(str(decision.cohort_digest) for decision in decisions),
        scenarios=scenarios,
        reasons=tuple(reasons),
    )


__all__ = [
    "ARTIFACT_FILES",
    "EXECUTION_BAR_COLUMNS",
    "EXECUTION_TERM_COLUMNS",
    "HOLDOUT_START_UTC",
    "INITIAL_CAPITAL_QUOTE_USDT",
    "MAX_SYMBOL_RULE_AGE",
    "REAL_ARTIFACT_KIND",
    "SCHEMA_VERSION",
    "SYNTHETIC_ARTIFACT_KIND",
    "XSMOMDevelopmentEvidenceError",
    "XSMOMDevelopmentExecution",
    "XSMOMDevelopmentManifest",
    "XSMOMDevelopmentPerformance",
    "XSMOMDevelopmentScenario",
    "XSMOMDevelopmentVerdict",
    "evaluate_xsmom_development",
]
