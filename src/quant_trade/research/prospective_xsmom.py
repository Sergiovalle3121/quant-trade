"""Sealed cross-sectional crypto momentum intentions, research only.

This module is deliberately isolated.  It has no loader, evaluator, registry,
network client, or execution path.  The caller supplies point-in-time rows and
receives a Thursday decision whose only permitted execution instant is the
following Friday open.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from numbers import Integral
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pandas as pd
import yaml

from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_text

SCHEMA_VERSION = 1
STRATEGY_ID = "binance_liquid_xsmom_30d_top20_weekly_v1"
CAMPAIGN_MODE = "PROSPECTIVE_DECLARATION_BLOCKED"
VENUE = "Binance"
MARKET = "Spot"
QUOTE_ASSET = "USDT"
SPEC_SEAL = "906e9dd5a0bd449dbc344921aea033456976132a3487a88f8b8fe1ce85010fdf"

_EXPECTED_UNIVERSE_POLICY = {
    "stable_identity": "CMC:<cmc_id>",
    "market_cap_min_usd_inclusive": 10_000_000.0,
    "market_cap_max_usd_inclusive": 1_000_000_000.0,
    "classification_flags_required_false": [
        "is_stablecoin",
        "is_wrapped_asset",
        "is_leveraged_token",
        "is_derivative_token",
        "is_rebase_token",
    ],
    "unknown_classification_action": "NO_SIGNAL",
    "eligibility_fields_required_true": ["eligible_to_open", "tradable"],
    "point_in_time_availability_field": "universe_observed_at_utc",
    "classification_availability_field": "classification_public_known_at_utc",
    "classification_interval": "valid_from_inclusive_valid_to_exclusive",
    "classification_open_end_representation": "EXPLICIT_NULL_ONLY_INVALID_TEXT_REJECTED",
    "venue_binding_availability_field": "venue_symbol_bound_at_utc",
    "required_venue": "Binance",
    "required_market": "Spot",
    "required_data_status": "VALID",
    "venue_symbol_pattern": "NONEMPTY_ASCII_ALNUM_BASE_PLUS_USDT",
    "venue_symbol_unique_per_timestamp": True,
}
_EXPECTED_SIGNAL_POLICY = {
    "decision_frequency": "weekly",
    "decision_weekday": "THURSDAY",
    "decision_timestamp": "THURSDAY_00_00_UTC",
    "latest_signal_bar": "WEDNESDAY_00_00_TO_THURSDAY_00_00_UTC",
    "required_close_count": 31,
    "momentum_lookback_calendar_days": 30,
    "momentum_return": "close_wednesday_t_over_close_t_minus_30_days_minus_1",
    "liquidity_window_calendar_days": 30,
    "liquidity_window": "t_minus_29_days_through_t_inclusive",
    "liquidity_daily_quote_volume_floor_usd": 5_000_000.0,
    "liquidity_minimum_passing_days": 15,
    "liquidity_score": "median_venue_turnover_usd_over_exact_30_day_window",
    "parent_cohort_size": 100,
    "portfolio_size": 20,
    "parent_sort": "liquidity_desc_then_cmc_id_numeric_asc",
    "candidate_sort": "momentum_desc_then_cmc_id_numeric_asc",
    "missing_or_gapped_history_action": "NO_SIGNAL",
    "fewer_than_100_eligible_action": "NO_SIGNAL",
    "fallback_allowed": False,
    "substitution_allowed": False,
    "stops_allowed": False,
}
_EXPECTED_PORTFOLIO_POLICY = {
    "candidate": "top20_momentum_within_top100_liquidity",
    "liquidity_control": "top20_liquidity_within_identical_top100_cohort",
    "target_weight_per_asset": 0.0475,
    "gross_target_weight": 0.95,
    "cash_reserve_weight": 0.05,
    "rebalance_interval_calendar_days": 7,
    "research_capital_usd": 200.0,
    "research_target_notional_per_leg_usd": 9.5,
    "missing_selected_leg_rule": "NO_SIGNAL_IF_MIN_NOTIONAL_PRECHECK_FAILS_NO_REPLACEMENT",
    "delta_below_minimum_action": "REFUSE_VISIBLY_NO_SUPPRESSION_OR_REDISTRIBUTION",
}
_EXPECTED_EXECUTION_POLICY = {
    "decision_to_execution_calendar_days": 1,
    "only_execution_instant": "FRIDAY_00_00_UTC_OPEN",
    "missing_exact_friday_open_action": "EXPIRE_NO_RETRY",
    "next_observed_bar_fallback_allowed": False,
    "same_boundary_execution_allowed": False,
    "min_notional_availability_field": "symbol_rules_observed_at_utc",
    "research_min_notional_screen_usd": 9.5,
    "min_notional_precheck_does_not_establish_executability": True,
    "full_execution_filters_and_friday_price_required_before_evaluation": True,
    "target_execution_status": "PENDING_EXECUTION_VALIDATION",
}
_EXPECTED_BENCHMARKS = [
    {
        "benchmark_id": "btc_usdt_buy_and_hold_comparable",
        "start": "same_first_friday_open",
        "btc_weight": 0.95,
        "cash_weight": 0.05,
        "same_costs": True,
    },
    {
        "benchmark_id": "btc_usdt_buy_and_hold_full_gate_required",
        "start": "same_first_friday_open",
        "btc_weight": 1.0,
        "same_costs": True,
    },
    {
        "benchmark_id": "top20_liquidity_control",
        "cohort": "identical_top100_liquidity_cohort_and_digest",
        "weight_per_asset": 0.0475,
        "cash_weight": 0.05,
        "same_dates_costs_and_execution_rules": True,
    },
]
_EXPECTED_EVIDENCE_POLICY = {
    "external_evidence": "MIXED_NOT_AN_EXACT_REPLICATION",
    "development_or_holdout_window_activated": False,
    "economic_evaluation_allowed": False,
    "independent_preregistration_timestamp_exists": False,
    "preregistration_claim_before_commit_allowed": False,
    "canonical_output_digests": ["cohort", "scores", "paired_target_set"],
    "digest_binding": "schema_decision_spec_identity_venue_scores_weights",
    "candidate_control_same_cohort_digest_required": True,
    "output_timestamps": "TIMEZONE_AWARE_UTC_ONLY",
    "cohort_score_order": "LIQUIDITY_DESC_THEN_CMC_ID_NUMERIC_ASC",
    "selected_min_notional_precheck_must_remain_true": True,
    "prior_failed_campaigns_preserved": [
        "binance_btc_eth_tsmom_long_cash_v1",
        "binance_btc_weekly_momentum_1w_long_cash_v1",
    ],
}
_EXPECTED_PROMOTION_BLOCKERS = {
    "current_panel": "INVALID_LOOKAHEAD",
    "stablecoin_point_in_time_evidence": "UNKNOWN_IN_CURRENT_PANEL",
    "gate0": "BINANCE_VENUE_POLICY_NOT_APPROVED",
    "pbo": "NOT_IDENTIFIABLE_SINGLE_TRIAL",
    "frequency": "WEEKLY_CONFLICTS_WITH_CURRENT_ANNUAL_COST_EVIDENCE",
    "costs": "ACCOUNT_AND_SYMBOL_SPECIFIC_COSTS_NOT_BOUND",
    "minimum_notional": "POINT_IN_TIME_SYMBOL_RULES_DATASET_NOT_BUILT",
    "maximum_verdict": "INSUFFICIENT_EVIDENCE",
}
_EXPECTED_AUTHORIZATION = {
    "research_only": True,
    "generic_runner_enabled": False,
    "strategy_registry_enabled": False,
    "network_access_enabled": False,
    "live_execution_enabled": False,
    "real_money_authorized": False,
    "external_action_authorized": False,
}

REQUIRED_COLUMNS = (
    "instrument_id",
    "cmc_id",
    "venue_symbol",
    "venue",
    "market",
    "data_status",
    "timestamp",
    "bar_closed_at_utc",
    "venue_symbol_bound_at_utc",
    "universe_observed_at_utc",
    "classification_public_known_at_utc",
    "classification_valid_from_utc",
    "classification_valid_to_utc",
    "symbol_rules_observed_at_utc",
    "close",
    "venue_turnover_usd",
    "market_cap_usd",
    "eligible_to_open",
    "tradable",
    "is_stablecoin",
    "is_wrapped_asset",
    "is_leveraged_token",
    "is_derivative_token",
    "is_rebase_token",
    "min_notional_usd",
)
_STRICT_BOOLS = (
    "eligible_to_open",
    "tradable",
    "is_stablecoin",
    "is_wrapped_asset",
    "is_leveraged_token",
    "is_derivative_token",
    "is_rebase_token",
)
_CLASSIFICATION_FLAGS = _STRICT_BOOLS[2:]


class XSMOMError(ValueError):
    """Raised when a declaration or point-in-time input violates the seal."""


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise XSMOMError("XSMOM specs reject NaN and infinity")
        return value
    raise XSMOMError(f"XSMOM specs accept JSON-shaped values, got {type(value).__name__}")


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _require_exact(name: str, observed: Any, expected: Any) -> None:
    if canonical_dumps(_thaw(_freeze(observed))) != canonical_dumps(expected):
        raise XSMOMError(f"{name} contradicts the sealed XSMOM campaign")


@dataclass(frozen=True)
class XSMOMSpec:
    """Deeply immutable, content-addressed declaration for one trial."""

    schema_version: int
    strategy_id: str
    campaign_mode: str
    venue: str
    market: str
    quote_asset: str
    universe_policy: Mapping[str, Any]
    signal_policy: Mapping[str, Any]
    portfolio_policy: Mapping[str, Any]
    execution_policy: Mapping[str, Any]
    benchmarks: Sequence[Mapping[str, Any]]
    trial_budget: int
    evidence_policy: Mapping[str, Any]
    promotion_blockers: Mapping[str, Any]
    authorization: Mapping[str, Any]

    def __post_init__(self) -> None:
        for name in (
            "universe_policy",
            "signal_policy",
            "portfolio_policy",
            "execution_policy",
            "evidence_policy",
            "promotion_blockers",
            "authorization",
        ):
            value = getattr(self, name)
            if not isinstance(value, Mapping):
                raise XSMOMError(f"{name} must be a mapping")
            object.__setattr__(self, name, _freeze(value))
        if not isinstance(self.benchmarks, (list, tuple)):
            raise XSMOMError("benchmarks must be a sequence")
        object.__setattr__(self, "benchmarks", _freeze(self.benchmarks))
        expected = {
            "schema_version": SCHEMA_VERSION,
            "strategy_id": STRATEGY_ID,
            "campaign_mode": CAMPAIGN_MODE,
            "venue": VENUE,
            "market": MARKET,
            "quote_asset": QUOTE_ASSET,
            "universe_policy": _EXPECTED_UNIVERSE_POLICY,
            "signal_policy": _EXPECTED_SIGNAL_POLICY,
            "portfolio_policy": _EXPECTED_PORTFOLIO_POLICY,
            "execution_policy": _EXPECTED_EXECUTION_POLICY,
            "benchmarks": _EXPECTED_BENCHMARKS,
            "trial_budget": 1,
            "evidence_policy": _EXPECTED_EVIDENCE_POLICY,
            "promotion_blockers": _EXPECTED_PROMOTION_BLOCKERS,
            "authorization": _EXPECTED_AUTHORIZATION,
        }
        for name, fixed in expected.items():
            _require_exact(name, getattr(self, name), fixed)

    def canonical_payload(self) -> dict[str, Any]:
        return {field.name: _thaw(getattr(self, field.name)) for field in fields(self)}

    def seal(self) -> str:
        return sha256_of_text(canonical_dumps(self.canonical_payload()))


@dataclass(frozen=True)
class XSMOMScore:
    instrument_id: str
    cmc_id: int
    venue_symbol: str
    momentum_return: float
    liquidity_median_usd: float
    min_notional_precheck_passed: bool

    def __post_init__(self) -> None:
        if (
            isinstance(self.cmc_id, bool)
            or not isinstance(self.cmc_id, Integral)
            or self.cmc_id < 1
        ):
            raise XSMOMError("score cmc_id must be a positive integer, not bool")
        if self.instrument_id != f"CMC:{self.cmc_id}":
            raise XSMOMError("score instrument_id must equal CMC:<cmc_id>")
        if not _valid_venue_symbol(self.venue_symbol):
            raise XSMOMError("score venue_symbol must name a non-empty USDT base")
        if not math.isfinite(self.momentum_return) or not math.isfinite(self.liquidity_median_usd):
            raise XSMOMError("score values must be finite")
        if self.liquidity_median_usd < 0:
            raise XSMOMError("score liquidity cannot be negative")
        if type(self.min_notional_precheck_passed) is not bool:
            raise XSMOMError("minimum-notional precheck must be an actual boolean")


@dataclass(frozen=True)
class XSMOMTarget:
    strategy_id: str
    strategy_spec_seal: str
    trial_number: int
    portfolio: str
    decision_timestamp: pd.Timestamp
    exact_execution_timestamp: pd.Timestamp
    expiration_timestamp: pd.Timestamp
    instrument_id: str
    cmc_id: int
    venue_symbol: str
    target_weight: float
    momentum_return: float
    liquidity_median_usd: float
    cohort_digest: str
    score_digest: str
    target_set_digest: str
    order_intent: str = "RESEARCH_TARGET_ONLY"
    execution_status: str = "PENDING_EXECUTION_VALIDATION"
    real_money_authorized: bool = False

    def __post_init__(self) -> None:
        if self.strategy_id != STRATEGY_ID or self.trial_number != 1:
            raise XSMOMError("target strategy identity and trial number are sealed")
        if self.portfolio not in {"CANDIDATE_XSMOM", "LIQUIDITY_CONTROL"}:
            raise XSMOMError("target portfolio is invalid")
        if self.strategy_spec_seal != SPEC_SEAL:
            raise XSMOMError("target strategy seal is not the sealed XSMOM declaration")
        for name in ("cohort_digest", "score_digest", "target_set_digest"):
            digest = getattr(self, name)
            if len(digest) != 64 or any(
                character not in "0123456789abcdef" for character in digest
            ):
                raise XSMOMError(f"{name} must be lowercase SHA-256")
        if (
            isinstance(self.cmc_id, bool)
            or not isinstance(self.cmc_id, Integral)
            or self.cmc_id < 1
        ):
            raise XSMOMError("target cmc_id must be a positive integer, not bool")
        if self.instrument_id != f"CMC:{self.cmc_id}":
            raise XSMOMError("target instrument_id must equal CMC:<cmc_id>")
        if not _valid_venue_symbol(self.venue_symbol):
            raise XSMOMError("target venue_symbol must name a non-empty USDT base")
        for name in (
            "decision_timestamp",
            "exact_execution_timestamp",
            "expiration_timestamp",
        ):
            _require_utc_timestamp(name, getattr(self, name))
        if self.decision_timestamp.dayofweek != 3 or (
            self.decision_timestamp != self.decision_timestamp.normalize()
        ):
            raise XSMOMError("target decision must be Thursday 00:00 UTC")
        expected_execution = self.decision_timestamp + pd.Timedelta(days=1)
        if self.exact_execution_timestamp != expected_execution:
            raise XSMOMError("target execution must be the exact Friday 00:00 UTC open")
        if self.expiration_timestamp != expected_execution:
            raise XSMOMError("target must expire at its sole Friday execution instant")
        if self.target_weight != 0.0475:
            raise XSMOMError("target weight must be exactly 4.75%")
        if not math.isfinite(self.momentum_return) or not math.isfinite(self.liquidity_median_usd):
            raise XSMOMError("target scores must be finite")
        if self.liquidity_median_usd < 0:
            raise XSMOMError("target liquidity cannot be negative")
        if self.order_intent != "RESEARCH_TARGET_ONLY":
            raise XSMOMError("target order_intent is sealed to research only")
        if self.execution_status != "PENDING_EXECUTION_VALIDATION":
            raise XSMOMError("target execution must remain pending independent validation")
        if type(self.real_money_authorized) is not bool or self.real_money_authorized:
            raise XSMOMError("target can never authorize real money")


@dataclass(frozen=True)
class XSMOMDecision:
    status: str
    reason: str
    decision_timestamp: pd.Timestamp
    exact_execution_timestamp: pd.Timestamp
    expiration_timestamp: pd.Timestamp
    cohort_instrument_ids: tuple[str, ...] = ()
    cohort_digest: str | None = None
    score_digest: str | None = None
    target_set_digest: str | None = None
    cohort_scores: tuple[XSMOMScore, ...] = ()
    candidate_targets: tuple[XSMOMTarget, ...] = ()
    liquidity_control_targets: tuple[XSMOMTarget, ...] = ()
    strategy_id: str = STRATEGY_ID
    strategy_spec_seal: str = SPEC_SEAL
    trial_number: int = 1

    def __post_init__(self) -> None:
        if (
            self.strategy_id != STRATEGY_ID
            or self.strategy_spec_seal != SPEC_SEAL
            or self.trial_number != 1
        ):
            raise XSMOMError("decision strategy identity, seal and trial number are fixed")
        for name in (
            "decision_timestamp",
            "exact_execution_timestamp",
            "expiration_timestamp",
        ):
            _require_utc_timestamp(name, getattr(self, name))
        if self.decision_timestamp.dayofweek != 3 or (
            self.decision_timestamp != self.decision_timestamp.normalize()
        ):
            raise XSMOMError("decision must be Thursday 00:00 UTC")
        expected_execution = self.decision_timestamp + pd.Timedelta(days=1)
        if self.exact_execution_timestamp != expected_execution:
            raise XSMOMError("decision execution must be exact Friday 00:00 UTC")
        if self.expiration_timestamp != expected_execution:
            raise XSMOMError("decision must expire at exact Friday 00:00 UTC")
        if self.status == "NO_SIGNAL":
            allowed_reasons = {
                "NO_CAUSAL_ROWS_IN_EXACT_31_DAY_WINDOW",
                "FEWER_THAN_100_CAUSALLY_ELIGIBLE_INSTRUMENTS",
                "SELECTED_LEG_FAILS_USD_9_50_MIN_NOTIONAL_PRECHECK_NO_SUBSTITUTION",
            }
            if self.reason not in allowed_reasons:
                raise XSMOMError("NO_SIGNAL reason is not a sealed outcome")
            if any(
                (
                    self.cohort_instrument_ids,
                    self.cohort_digest,
                    self.score_digest,
                    self.target_set_digest,
                    self.cohort_scores,
                    self.candidate_targets,
                    self.liquidity_control_targets,
                )
            ):
                raise XSMOMError("NO_SIGNAL decisions cannot carry cohorts or targets")
            return
        if self.status != "TARGETS_CREATED_RESEARCH_ONLY" or self.reason != (
            "EXACT_FRIDAY_OPEN_INTENTIONS_NOT_ORDERS"
        ):
            raise XSMOMError("decision status and reason are sealed to research outcomes")
        if len(self.cohort_instrument_ids) != 100 or len(set(self.cohort_instrument_ids)) != 100:
            raise XSMOMError("a target decision requires 100 unique cohort identities")
        if len(self.cohort_scores) != 100:
            raise XSMOMError("a target decision requires 100 complete cohort scores")
        expected_score_order = tuple(
            sorted(
                self.cohort_scores,
                key=lambda score: (-score.liquidity_median_usd, score.cmc_id),
            )
        )
        if self.cohort_scores != expected_score_order:
            raise XSMOMError("cohort scores must remain in sealed liquidity/cmc_id order")
        score_ids = tuple(score.instrument_id for score in self.cohort_scores)
        if score_ids != self.cohort_instrument_ids:
            raise XSMOMError("cohort identities and ordered scores must match")
        venue_symbols = tuple(score.venue_symbol for score in self.cohort_scores)
        if len(set(venue_symbols)) != 100:
            raise XSMOMError("cohort venue symbols must be unique")
        expected_candidate = tuple(
            score.instrument_id
            for score in sorted(
                self.cohort_scores,
                key=lambda score: (-score.momentum_return, score.cmc_id),
            )[:20]
        )
        expected_control = tuple(score.instrument_id for score in self.cohort_scores[:20])
        scores_by_id = {score.instrument_id: score for score in self.cohort_scores}
        selected_ids = (*expected_candidate, *expected_control)
        if any(
            not scores_by_id[instrument_id].min_notional_precheck_passed
            for instrument_id in selected_ids
        ):
            raise XSMOMError(
                "every selected candidate/control score must pass min-notional precheck"
            )
        expected_cohort_digest = _cohort_digest(
            self.decision_timestamp,
            self.strategy_spec_seal,
            self.cohort_scores,
        )
        if self.cohort_digest != expected_cohort_digest:
            raise XSMOMError("decision cohort digest does not match its causal scores")
        if self.score_digest is None or self.target_set_digest is None:
            raise XSMOMError("target decisions require score and target-set digests")
        expected_score_digest = _score_digest(
            self.decision_timestamp,
            self.strategy_spec_seal,
            self.cohort_scores,
        )
        if self.score_digest != expected_score_digest:
            raise XSMOMError("decision score digest does not match its score payload")
        if len(self.candidate_targets) != 20 or len(self.liquidity_control_targets) != 20:
            raise XSMOMError("a target decision requires two complete 20-leg portfolios")
        all_targets = (*self.candidate_targets, *self.liquidity_control_targets)
        if any(target.cohort_digest != self.cohort_digest for target in all_targets):
            raise XSMOMError("all paired targets must bind the same cohort digest")
        if any(target.score_digest != self.score_digest for target in all_targets):
            raise XSMOMError("all paired targets must bind the same score digest")
        if any(target.target_set_digest != self.target_set_digest for target in all_targets):
            raise XSMOMError("all paired targets must bind the same target-set digest")
        if any(target.decision_timestamp != self.decision_timestamp for target in all_targets):
            raise XSMOMError("all targets must bind the decision timestamp")
        if any(target.portfolio != "CANDIDATE_XSMOM" for target in self.candidate_targets):
            raise XSMOMError("candidate targets have the wrong portfolio identity")
        if any(
            target.portfolio != "LIQUIDITY_CONTROL" for target in self.liquidity_control_targets
        ):
            raise XSMOMError("control targets have the wrong portfolio identity")
        if tuple(target.instrument_id for target in self.candidate_targets) != expected_candidate:
            raise XSMOMError("candidate targets do not match the sealed momentum ranking")
        if tuple(target.instrument_id for target in self.liquidity_control_targets) != (
            expected_control
        ):
            raise XSMOMError("control targets do not match the sealed liquidity ranking")
        for target in all_targets:
            score = scores_by_id[target.instrument_id]
            if (
                target.cmc_id != score.cmc_id
                or target.venue_symbol != score.venue_symbol
                or target.momentum_return != score.momentum_return
                or target.liquidity_median_usd != score.liquidity_median_usd
            ):
                raise XSMOMError("target identity and scores must match the cohort score")
        expected_target_set_digest = _target_set_digest(
            self.decision_timestamp,
            self.strategy_spec_seal,
            self.cohort_digest,
            self.score_digest,
            self.candidate_targets,
            self.liquidity_control_targets,
        )
        if self.target_set_digest != expected_target_set_digest:
            raise XSMOMError("decision target-set digest does not match its paired targets")


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_dumps(value).encode()).hexdigest()


def _require_utc_timestamp(name: str, value: Any) -> None:
    if not isinstance(value, pd.Timestamp) or value.tzinfo is None:
        raise XSMOMError(f"{name} must be a timezone-aware pandas UTC timestamp")
    if value.utcoffset() != pd.Timedelta(0):
        raise XSMOMError(f"{name} must use UTC offset zero")


def _score_payload(score: XSMOMScore) -> dict[str, Any]:
    return {
        "instrument_id": score.instrument_id,
        "cmc_id": int(score.cmc_id),
        "venue_symbol": score.venue_symbol,
        "momentum_return": score.momentum_return,
        "liquidity_median_usd": score.liquidity_median_usd,
        "min_notional_precheck_passed": score.min_notional_precheck_passed,
    }


def _digest_envelope(
    decision_timestamp: pd.Timestamp,
    strategy_spec_seal: str,
    kind: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "strategy_id": STRATEGY_ID,
        "strategy_spec_seal": strategy_spec_seal,
        "decision_timestamp": decision_timestamp.isoformat(),
        "digest_kind": kind,
    }


def _cohort_digest(
    decision_timestamp: pd.Timestamp,
    strategy_spec_seal: str,
    scores: Sequence[XSMOMScore],
) -> str:
    payload = _digest_envelope(decision_timestamp, strategy_spec_seal, "COHORT")
    payload["cohort"] = [
        {
            "instrument_id": score.instrument_id,
            "cmc_id": int(score.cmc_id),
            "venue_symbol": score.venue_symbol,
            "liquidity_median_usd": score.liquidity_median_usd,
        }
        for score in scores
    ]
    return _digest(payload)


def _score_digest(
    decision_timestamp: pd.Timestamp,
    strategy_spec_seal: str,
    scores: Sequence[XSMOMScore],
) -> str:
    payload = _digest_envelope(decision_timestamp, strategy_spec_seal, "SCORES")
    payload["scores"] = [_score_payload(score) for score in scores]
    return _digest(payload)


def _target_payload(target: XSMOMTarget) -> dict[str, Any]:
    return {
        "portfolio": target.portfolio,
        "instrument_id": target.instrument_id,
        "cmc_id": int(target.cmc_id),
        "venue_symbol": target.venue_symbol,
        "target_weight": target.target_weight,
        "momentum_return": target.momentum_return,
        "liquidity_median_usd": target.liquidity_median_usd,
        "execution_status": target.execution_status,
        "real_money_authorized": target.real_money_authorized,
    }


def _target_set_digest(
    decision_timestamp: pd.Timestamp,
    strategy_spec_seal: str,
    cohort_digest: str,
    score_digest: str,
    candidate_targets: Sequence[XSMOMTarget],
    control_targets: Sequence[XSMOMTarget],
) -> str:
    payload = _digest_envelope(decision_timestamp, strategy_spec_seal, "TARGET_SET")
    payload.update(
        {
            "cohort_digest": cohort_digest,
            "score_digest": score_digest,
            "candidate_targets": [_target_payload(target) for target in candidate_targets],
            "liquidity_control_targets": [_target_payload(target) for target in control_targets],
        }
    )
    return _digest(payload)


def _target_set_digest_from_scores(
    decision_timestamp: pd.Timestamp,
    strategy_spec_seal: str,
    cohort_digest: str,
    score_digest: str,
    candidate_scores: Sequence[XSMOMScore],
    control_scores: Sequence[XSMOMScore],
) -> str:
    def payload(portfolio: str, score: XSMOMScore) -> dict[str, Any]:
        return {
            "portfolio": portfolio,
            "instrument_id": score.instrument_id,
            "cmc_id": int(score.cmc_id),
            "venue_symbol": score.venue_symbol,
            "target_weight": 0.0475,
            "momentum_return": score.momentum_return,
            "liquidity_median_usd": score.liquidity_median_usd,
            "execution_status": "PENDING_EXECUTION_VALIDATION",
            "real_money_authorized": False,
        }

    envelope = _digest_envelope(decision_timestamp, strategy_spec_seal, "TARGET_SET")
    envelope.update(
        {
            "cohort_digest": cohort_digest,
            "score_digest": score_digest,
            "candidate_targets": [payload("CANDIDATE_XSMOM", score) for score in candidate_scores],
            "liquidity_control_targets": [
                payload("LIQUIDITY_CONTROL", score) for score in control_scores
            ],
        }
    )
    return _digest(envelope)


def _valid_venue_symbol(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and value == value.strip().upper()
        and re.fullmatch(r"[A-Z0-9]+USDT", value)
        and len(value) > len(QUOTE_ASSET)
    )


def load_xsmom_spec(path: str | Path) -> XSMOMSpec:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise XSMOMError("XSMOM config must contain a mapping")
    seal = raw.pop("seal", None)
    if (
        not isinstance(seal, str)
        or len(seal) != 64
        or any(c not in "0123456789abcdef" for c in seal)
    ):
        raise XSMOMError("XSMOM config requires a lowercase 64-character seal")
    expected_fields = {field.name for field in fields(XSMOMSpec)}
    missing = sorted(expected_fields - set(raw))
    unknown = sorted(set(raw) - expected_fields)
    if missing or unknown:
        raise XSMOMError(f"XSMOM config fields mismatch; missing={missing}, unknown={unknown}")
    try:
        spec = XSMOMSpec(**raw)
    except TypeError as exc:
        raise XSMOMError(f"invalid XSMOM config: {exc}") from exc
    if spec.seal() != seal:
        raise XSMOMError("XSMOM config seal mismatch")
    return spec


def _utc(name: str, value: Any) -> pd.Timestamp:
    parsed = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(parsed):
        raise XSMOMError(f"{name} must be a valid UTC timestamp")
    return pd.Timestamp(parsed)


def _no_signal(decision: pd.Timestamp, reason: str) -> XSMOMDecision:
    execution = decision + pd.Timedelta(days=1)
    return XSMOMDecision("NO_SIGNAL", reason, decision, execution, execution)


def _validate_spec(spec: XSMOMSpec) -> None:
    if not isinstance(spec, XSMOMSpec):
        raise XSMOMError("an XSMOMSpec is required")
    reconstructed = XSMOMSpec(**spec.canonical_payload())
    if reconstructed.seal() != spec.seal() or spec.seal() != SPEC_SEAL:
        raise XSMOMError("an invalid XSMOM spec was supplied")


def build_xsmom_decision(
    panel_rows: pd.DataFrame,
    spec: XSMOMSpec,
    decision_timestamp: str | pd.Timestamp,
) -> XSMOMDecision:
    """Build one causal Thursday target decision without evaluating returns."""

    _validate_spec(spec)
    decision = _utc("decision_timestamp", decision_timestamp)
    if decision.dayofweek != 3 or decision != decision.normalize():
        raise XSMOMError("decision_timestamp must be Thursday 00:00 UTC")
    missing = [name for name in REQUIRED_COLUMNS if name not in panel_rows.columns]
    if missing:
        raise XSMOMError(f"XSMOM panel is missing required columns: {missing}")

    frame = panel_rows.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    if frame["timestamp"].isna().any():
        raise XSMOMError("timestamp must contain valid UTC timestamps")
    latest_start = decision - pd.Timedelta(days=1)
    reference_start = latest_start - pd.Timedelta(days=30)
    causal = frame[frame["timestamp"].between(reference_start, latest_start)].copy()
    if causal.empty:
        return _no_signal(decision, "NO_CAUSAL_ROWS_IN_EXACT_31_DAY_WINDOW")
    if causal.duplicated(["instrument_id", "timestamp"]).any():
        raise XSMOMError("duplicate instrument_id/timestamp rows are forbidden")
    if not bool(causal["timestamp"].dt.normalize().eq(causal["timestamp"]).all()):
        raise XSMOMError("bars must start at 00:00 UTC")
    if not bool(causal["venue"].eq(VENUE).all()):
        raise XSMOMError("every contributing row must be bound to Binance")
    if not bool(causal["market"].eq(MARKET).all()):
        raise XSMOMError("every contributing row must be bound to Spot")
    if not bool(causal["data_status"].eq("VALID").all()):
        raise XSMOMError("every contributing row must have VALID data_status")
    if any(not _valid_venue_symbol(value) for value in causal["venue_symbol"]):
        raise XSMOMError("every venue_symbol must name a non-empty alphanumeric USDT base")
    if causal.duplicated(["timestamp", "venue_symbol"]).any():
        raise XSMOMError("a venue symbol cannot bind multiple stable identities on one bar")
    for raw_cmc_id in causal["cmc_id"]:
        if isinstance(raw_cmc_id, bool) or not isinstance(raw_cmc_id, Integral) or raw_cmc_id <= 0:
            raise XSMOMError("every cmc_id must be a positive integer, not bool")

    for name in _STRICT_BOOLS:
        if causal[name].isna().any() or any(type(value) is not bool for value in causal[name]):
            raise XSMOMError(f"{name} must contain actual booleans; UNKNOWN fails closed")
    for name in ("close", "venue_turnover_usd", "market_cap_usd", "min_notional_usd"):
        causal[name] = pd.to_numeric(causal[name], errors="coerce")
        if causal[name].isna().any() or not bool(causal[name].map(math.isfinite).all()):
            raise XSMOMError(f"{name} must contain finite numbers")
    if (causal["close"] <= 0).any() or (causal["venue_turnover_usd"] < 0).any():
        raise XSMOMError("prices must be positive and turnover non-negative")
    if (causal["market_cap_usd"] <= 0).any() or (causal["min_notional_usd"] <= 0).any():
        raise XSMOMError("market cap and minimum notional must be positive")

    for name in (
        "bar_closed_at_utc",
        "venue_symbol_bound_at_utc",
        "universe_observed_at_utc",
        "classification_public_known_at_utc",
        "classification_valid_from_utc",
        "symbol_rules_observed_at_utc",
    ):
        causal[name] = pd.to_datetime(causal[name], utc=True, errors="coerce")
        if causal[name].isna().any():
            raise XSMOMError(f"{name} must be known; UNKNOWN fails closed")
    raw_valid_to = causal["classification_valid_to_utc"].copy()
    causal["classification_valid_to_utc"] = pd.to_datetime(raw_valid_to, utc=True, errors="coerce")
    invalid_valid_to = raw_valid_to.notna() & causal["classification_valid_to_utc"].isna()
    if invalid_valid_to.any():
        raise XSMOMError(
            "classification_valid_to_utc must be a valid timestamp or explicit null for open end"
        )
    if not bool(causal["bar_closed_at_utc"].eq(causal["timestamp"] + pd.Timedelta(days=1)).all()):
        raise XSMOMError("each daily bar must close exactly one day after it starts")
    if (causal["bar_closed_at_utc"] > decision).any():
        raise XSMOMError("future or incomplete bars cannot enter a Thursday decision")
    if (causal["venue_symbol_bound_at_utc"] > causal["bar_closed_at_utc"]).any():
        raise XSMOMError("venue symbols must be causally bound before their bars close")
    metrics: list[dict[str, Any]] = []
    expected_days = pd.date_range(reference_start, latest_start, freq="D", tz="UTC")
    for instrument_id, group in causal.groupby("instrument_id", sort=False):
        group = group.sort_values("timestamp").reset_index(drop=True)
        if len(group) != 31 or not group["timestamp"].reset_index(drop=True).equals(
            pd.Series(expected_days, name="timestamp")
        ):
            continue
        latest = group.iloc[-1]
        raw_cmc_id = latest["cmc_id"]
        if isinstance(raw_cmc_id, bool) or not isinstance(raw_cmc_id, Integral) or raw_cmc_id <= 0:
            raise XSMOMError("cmc_id must be a positive integer, not bool")
        cmc_id = int(raw_cmc_id)
        if str(instrument_id) != f"CMC:{cmc_id}":
            raise XSMOMError("instrument_id must equal CMC:<cmc_id>")
        if group["cmc_id"].map(float).ne(float(cmc_id)).any():
            raise XSMOMError("stable identity cannot change inside the lookback")
        if any(
            latest[name] > decision
            for name in (
                "universe_observed_at_utc",
                "classification_public_known_at_utc",
                "symbol_rules_observed_at_utc",
            )
        ):
            continue
        valid_to = latest["classification_valid_to_utc"]
        if latest["classification_valid_from_utc"] > decision or (
            not pd.isna(valid_to) and decision >= valid_to
        ):
            continue
        if not bool(latest["eligible_to_open"]) or not bool(latest["tradable"]):
            continue
        if any(bool(latest[name]) for name in _CLASSIFICATION_FLAGS):
            continue
        cap = float(latest["market_cap_usd"])
        if not 10_000_000.0 <= cap <= 1_000_000_000.0:
            continue
        window = group.iloc[-30:]
        passing_days = int((window["venue_turnover_usd"] >= 5_000_000.0).sum())
        if passing_days < 15:
            continue
        venue_symbol = latest["venue_symbol"]
        if not _valid_venue_symbol(venue_symbol):
            raise XSMOMError("venue_symbol must name a non-empty alphanumeric USDT base")
        metrics.append(
            {
                "instrument_id": str(instrument_id),
                "cmc_id": cmc_id,
                "venue_symbol": venue_symbol,
                "momentum": float(group.iloc[-1]["close"] / group.iloc[0]["close"] - 1.0),
                "liquidity": float(window["venue_turnover_usd"].median()),
                "min_notional_precheck_passed": float(latest["min_notional_usd"]) <= 9.5,
            }
        )

    if len(metrics) < 100:
        return _no_signal(decision, "FEWER_THAN_100_CAUSALLY_ELIGIBLE_INSTRUMENTS")
    cohort = sorted(metrics, key=lambda item: (-item["liquidity"], item["cmc_id"]))[:100]
    venue_symbols = [item["venue_symbol"] for item in cohort]
    if len(venue_symbols) != len(set(venue_symbols)):
        raise XSMOMError("one cohort venue_symbol cannot bind multiple stable CMC identities")
    scores = tuple(
        XSMOMScore(
            instrument_id=item["instrument_id"],
            cmc_id=item["cmc_id"],
            venue_symbol=item["venue_symbol"],
            momentum_return=item["momentum"],
            liquidity_median_usd=item["liquidity"],
            min_notional_precheck_passed=item["min_notional_precheck_passed"],
        )
        for item in cohort
    )
    cohort_ids = tuple(score.instrument_id for score in scores)
    cohort_digest = _cohort_digest(decision, spec.seal(), scores)
    score_digest = _score_digest(decision, spec.seal(), scores)
    candidate = tuple(sorted(scores, key=lambda score: (-score.momentum_return, score.cmc_id))[:20])
    control = scores[:20]
    if any(not score.min_notional_precheck_passed for score in (*candidate, *control)):
        return _no_signal(
            decision,
            "SELECTED_LEG_FAILS_USD_9_50_MIN_NOTIONAL_PRECHECK_NO_SUBSTITUTION",
        )

    target_set_digest = _target_set_digest_from_scores(
        decision,
        spec.seal(),
        cohort_digest,
        score_digest,
        candidate,
        control,
    )

    execution = decision + pd.Timedelta(days=1)

    def targets(portfolio: str, selected: Sequence[XSMOMScore]) -> tuple[XSMOMTarget, ...]:
        return tuple(
            XSMOMTarget(
                strategy_id=spec.strategy_id,
                strategy_spec_seal=spec.seal(),
                trial_number=1,
                portfolio=portfolio,
                decision_timestamp=decision,
                exact_execution_timestamp=execution,
                expiration_timestamp=execution,
                instrument_id=item.instrument_id,
                cmc_id=item.cmc_id,
                venue_symbol=item.venue_symbol,
                target_weight=0.0475,
                momentum_return=item.momentum_return,
                liquidity_median_usd=item.liquidity_median_usd,
                cohort_digest=cohort_digest,
                score_digest=score_digest,
                target_set_digest=target_set_digest,
            )
            for item in selected
        )

    return XSMOMDecision(
        status="TARGETS_CREATED_RESEARCH_ONLY",
        reason="EXACT_FRIDAY_OPEN_INTENTIONS_NOT_ORDERS",
        decision_timestamp=decision,
        exact_execution_timestamp=execution,
        expiration_timestamp=execution,
        cohort_instrument_ids=cohort_ids,
        cohort_digest=cohort_digest,
        score_digest=score_digest,
        target_set_digest=target_set_digest,
        cohort_scores=scores,
        candidate_targets=targets("CANDIDATE_XSMOM", candidate),
        liquidity_control_targets=targets("LIQUIDITY_CONTROL", control),
    )


__all__ = [
    "CAMPAIGN_MODE",
    "MARKET",
    "QUOTE_ASSET",
    "REQUIRED_COLUMNS",
    "SCHEMA_VERSION",
    "STRATEGY_ID",
    "VENUE",
    "XSMOMDecision",
    "XSMOMError",
    "XSMOMScore",
    "XSMOMSpec",
    "XSMOMTarget",
    "build_xsmom_decision",
    "load_xsmom_spec",
]
