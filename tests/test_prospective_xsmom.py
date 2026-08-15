from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import yaml

from quant_trade.research.prospective_xsmom import (
    STRATEGY_ID,
    XSMOMError,
    XSMOMSpec,
    build_xsmom_decision,
    load_xsmom_spec,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "experiments" / "binance_liquid_xsmom_30d_top20_weekly_v1.yaml"
DECISION = pd.Timestamp("2024-02-01T00:00:00Z")  # Thursday


def _spec() -> XSMOMSpec:
    return load_xsmom_spec(CONFIG)


def _panel(count: int = 101) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    days = pd.date_range("2024-01-01", "2024-01-31", freq="D", tz="UTC")
    for cmc_id in range(1, count + 1):
        for offset, day in enumerate(days):
            close = 100.0 * (1.0 + (cmc_id / 1_000.0) * offset / 30.0)
            rows.append(
                {
                    "instrument_id": f"CMC:{cmc_id}",
                    "cmc_id": cmc_id,
                    "venue_symbol": f"A{cmc_id}USDT",
                    "venue": "Binance",
                    "market": "Spot",
                    "data_status": "VALID",
                    "timestamp": day,
                    "bar_closed_at_utc": day + pd.Timedelta(days=1),
                    "venue_symbol_bound_at_utc": "2023-01-01T00:00:00Z",
                    "universe_observed_at_utc": day + pd.Timedelta(days=1),
                    "classification_public_known_at_utc": "2023-01-01T00:00:00Z",
                    "classification_valid_from_utc": "2023-01-01T00:00:00Z",
                    "classification_valid_to_utc": None,
                    "symbol_rules_observed_at_utc": "2023-01-01T00:00:00Z",
                    "close": close,
                    "venue_turnover_usd": 20_000_000.0 - cmc_id * 1_000.0,
                    "market_cap_usd": 100_000_000.0,
                    "eligible_to_open": True,
                    "tradable": True,
                    "is_stablecoin": False,
                    "is_wrapped_asset": False,
                    "is_leveraged_token": False,
                    "is_derivative_token": False,
                    "is_rebase_token": False,
                    "symbol_rules_tradable": True,
                    "min_notional_usd": 5.0,
                }
            )
    return pd.DataFrame(rows)


def _latest_mask(panel: pd.DataFrame, cmc_id: int) -> pd.Series:
    return panel["instrument_id"].eq(f"CMC:{cmc_id}") & pd.to_datetime(
        panel["timestamp"], utc=True
    ).eq(pd.Timestamp("2024-01-31T00:00:00Z"))


def test_config_is_sealed_single_trial_and_cannot_authorize_money() -> None:
    spec = _spec()

    assert spec.strategy_id == STRATEGY_ID
    assert spec.trial_budget == 1
    assert spec.seal() == "906e9dd5a0bd449dbc344921aea033456976132a3487a88f8b8fe1ce85010fdf"
    assert spec.evidence_policy["external_evidence"] == "MIXED_NOT_AN_EXACT_REPLICATION"
    assert spec.evidence_policy["development_or_holdout_window_activated"] is False
    assert spec.evidence_policy["independent_preregistration_timestamp_exists"] is False
    assert spec.promotion_blockers["current_panel"] == "INVALID_LOOKAHEAD"
    assert spec.promotion_blockers["stablecoin_point_in_time_evidence"].startswith("UNKNOWN")
    assert spec.promotion_blockers["maximum_verdict"] == "INSUFFICIENT_EVIDENCE"
    assert spec.authorization["generic_runner_enabled"] is False
    assert spec.authorization["strategy_registry_enabled"] is False
    assert spec.authorization["network_access_enabled"] is False
    assert spec.authorization["live_execution_enabled"] is False
    assert spec.authorization["real_money_authorized"] is False


def test_spec_is_deeply_immutable_and_byte_tamper_fails(tmp_path: Path) -> None:
    spec = _spec()
    with pytest.raises(TypeError):
        spec.signal_policy["portfolio_size"] = 21  # type: ignore[index]

    raw = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    raw["signal_policy"]["portfolio_size"] = 21
    path = tmp_path / "tampered.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    with pytest.raises(XSMOMError, match="sealed XSMOM campaign"):
        load_xsmom_spec(path)


def test_resealed_live_or_parameter_change_fails() -> None:
    authorization = dict(_spec().authorization)
    authorization["live_execution_enabled"] = True
    with pytest.raises(XSMOMError, match="sealed XSMOM campaign"):
        replace(_spec(), authorization=authorization)

    payload = _spec().canonical_payload()
    payload["trial_budget"] = 2
    with pytest.raises(XSMOMError, match="sealed XSMOM campaign"):
        XSMOMSpec(**payload)


def test_thursday_decision_builds_paired_95_percent_targets_with_same_cohort() -> None:
    result = build_xsmom_decision(_panel(), _spec(), DECISION)

    assert result.status == "TARGETS_CREATED_RESEARCH_ONLY"
    assert len(result.cohort_instrument_ids) == 100
    assert len(result.candidate_targets) == len(result.liquidity_control_targets) == 20
    assert sum(target.target_weight for target in result.candidate_targets) == pytest.approx(0.95)
    assert sum(
        target.target_weight for target in result.liquidity_control_targets
    ) == pytest.approx(0.95)
    assert {target.cohort_digest for target in result.candidate_targets} == {result.cohort_digest}
    assert {target.cohort_digest for target in result.liquidity_control_targets} == {
        result.cohort_digest
    }
    assert not any(target.real_money_authorized for target in result.candidate_targets)


def test_exact_30_day_return_parent_first_and_numeric_ties() -> None:
    panel = _panel()
    # Equalize every momentum score: numeric cmc_id, not ASCII, must break ties.
    for cmc_id in range(1, 102):
        mask = panel["instrument_id"].eq(f"CMC:{cmc_id}")
        offsets = panel.loc[mask].groupby("instrument_id").cumcount()
        panel.loc[mask, "close"] = 100.0 * (1.0 + 0.01 * offsets / 30.0)
    result = build_xsmom_decision(panel, _spec(), DECISION)

    assert [target.cmc_id for target in result.candidate_targets] == list(range(1, 21))
    assert result.candidate_targets[0].momentum_return == pytest.approx(0.01)
    assert result.cohort_instrument_ids.index("CMC:2") < result.cohort_instrument_ids.index(
        "CMC:10"
    )
    # CMC:101 has the highest original momentum but is outside the top-100 liquidity parent.
    original = build_xsmom_decision(_panel(), _spec(), DECISION)
    assert "CMC:101" not in original.cohort_instrument_ids
    assert max(target.cmc_id for target in original.candidate_targets) == 100


@pytest.mark.parametrize("passing_days", [14, 15])
def test_liquidity_threshold_is_exactly_15_of_30(passing_days: int) -> None:
    panel = _panel(100)
    mask = panel["instrument_id"].eq("CMC:100")
    indexes = panel.index[mask][-30:]
    panel.loc[indexes, "venue_turnover_usd"] = 4_999_999.0
    panel.loc[indexes[:passing_days], "venue_turnover_usd"] = 5_000_000.0

    result = build_xsmom_decision(panel, _spec(), DECISION)
    if passing_days == 14:
        assert result.status == "NO_SIGNAL"
        assert result.reason == "FEWER_THAN_100_CAUSALLY_ELIGIBLE_INSTRUMENTS"
    else:
        assert result.status == "TARGETS_CREATED_RESEARCH_ONLY"


def test_any_gap_in_31_exact_daily_closes_removes_name_and_fails_under_100() -> None:
    panel = _panel(100)
    panel = panel[
        ~(
            panel["instrument_id"].eq("CMC:100")
            & pd.to_datetime(panel["timestamp"], utc=True).eq("2024-01-15")
        )
    ]
    result = build_xsmom_decision(panel, _spec(), DECISION)
    assert result.status == "NO_SIGNAL"
    assert result.reason == "FEWER_THAN_100_CAUSALLY_ELIGIBLE_INSTRUMENTS"


def test_fewer_than_100_never_builds_a_smaller_portfolio() -> None:
    result = build_xsmom_decision(_panel(99), _spec(), DECISION)
    assert result.status == "NO_SIGNAL"
    assert not result.candidate_targets


@pytest.mark.parametrize("column", ["eligible_to_open", "tradable"])
def test_explicit_point_in_time_eligibility_is_required(column: str) -> None:
    panel = _panel(100)
    panel.loc[_latest_mask(panel, 100), column] = False
    result = build_xsmom_decision(panel, _spec(), DECISION)
    assert result.reason == "FEWER_THAN_100_CAUSALLY_ELIGIBLE_INSTRUMENTS"


@pytest.mark.parametrize(
    "column",
    [
        "is_stablecoin",
        "is_wrapped_asset",
        "is_leveraged_token",
        "is_derivative_token",
        "is_rebase_token",
    ],
)
def test_each_point_in_time_asset_exclusion_is_fail_closed(column: str) -> None:
    panel = _panel(100)
    panel.loc[_latest_mask(panel, 100), column] = True
    result = build_xsmom_decision(panel, _spec(), DECISION)
    assert result.reason == "FEWER_THAN_100_CAUSALLY_ELIGIBLE_INSTRUMENTS"


@pytest.mark.parametrize("value", [None, "False", 0])
def test_unknown_or_non_boolean_classification_is_rejected(value: Any) -> None:
    panel = _panel()
    panel["is_stablecoin"] = panel["is_stablecoin"].astype(object)
    panel.loc[_latest_mask(panel, 1), "is_stablecoin"] = value
    with pytest.raises(XSMOMError, match="actual booleans"):
        build_xsmom_decision(panel, _spec(), DECISION)


@pytest.mark.parametrize(
    "column",
    [
        "universe_observed_at_utc",
        "classification_public_known_at_utc",
        "symbol_rules_observed_at_utc",
    ],
)
def test_facts_not_public_by_thursday_are_ineligible(column: str) -> None:
    panel = _panel(100)
    panel.loc[_latest_mask(panel, 100), column] = "2024-02-01T00:00:01Z"
    result = build_xsmom_decision(panel, _spec(), DECISION)
    assert result.reason == "FEWER_THAN_100_CAUSALLY_ELIGIBLE_INSTRUMENTS"


def test_classification_interval_must_cover_the_decision() -> None:
    panel = _panel(100)
    panel.loc[_latest_mask(panel, 100), "classification_valid_to_utc"] = "2024-02-01T00:00:00Z"
    result = build_xsmom_decision(panel, _spec(), DECISION)
    assert result.reason == "FEWER_THAN_100_CAUSALLY_ELIGIBLE_INSTRUMENTS"


def test_future_thursday_bar_and_fact_cannot_change_decision_bytes() -> None:
    panel = _panel()
    before = build_xsmom_decision(panel, _spec(), DECISION)
    future = panel[panel["timestamp"].eq(pd.Timestamp("2024-01-31T00:00:00Z"))].copy()
    future["timestamp"] = pd.Timestamp("2024-02-01T00:00:00Z")
    future["bar_closed_at_utc"] = pd.Timestamp("2024-02-02T00:00:00Z")
    future["close"] = 1e12
    future["venue_turnover_usd"] = 1.0
    future["is_stablecoin"] = True
    after = build_xsmom_decision(pd.concat([panel, future], ignore_index=True), _spec(), DECISION)
    assert after == before


def test_selected_min_notional_failure_blocks_pair_without_substituting_number_21() -> None:
    panel = _panel()
    # CMC:100 is the highest-momentum member of the parent cohort.
    panel.loc[_latest_mask(panel, 100), "min_notional_usd"] = 10.0
    result = build_xsmom_decision(panel, _spec(), DECISION)
    assert result.status == "NO_SIGNAL"
    assert result.reason == ("SELECTED_LEG_FAILS_USD_9_50_MIN_NOTIONAL_PRECHECK_NO_SUBSTITUTION")
    assert not result.candidate_targets


def test_unselected_min_notional_failure_does_not_rewrite_the_parent_cohort() -> None:
    panel = _panel()
    # CMC:50 is neither candidate (81..100) nor liquidity control (1..20).
    panel.loc[_latest_mask(panel, 50), "min_notional_usd"] = 10.0
    result = build_xsmom_decision(panel, _spec(), DECISION)
    assert result.status == "TARGETS_CREATED_RESEARCH_ONLY"
    assert "CMC:50" in result.cohort_instrument_ids


def test_execution_is_exact_friday_and_missing_bar_can_only_expire_without_retry() -> None:
    # The signal input deliberately has no Friday row; this module schedules no fill.
    result = build_xsmom_decision(_panel(), _spec(), DECISION)
    friday = pd.Timestamp("2024-02-02T00:00:00Z")
    assert result.exact_execution_timestamp == friday
    assert result.expiration_timestamp == friday
    assert all(target.exact_execution_timestamp == friday for target in result.candidate_targets)
    assert all(target.expiration_timestamp == friday for target in result.candidate_targets)
    assert _spec().execution_policy["next_observed_bar_fallback_allowed"] is False


def test_wrong_weekday_missing_contract_and_unstable_identity_fail() -> None:
    with pytest.raises(XSMOMError, match="Thursday"):
        build_xsmom_decision(_panel(), _spec(), "2024-02-02T00:00:00Z")
    with pytest.raises(XSMOMError, match="missing required columns"):
        build_xsmom_decision(_panel().drop(columns=["bar_closed_at_utc"]), _spec(), DECISION)

    panel = _panel()
    panel.loc[panel["instrument_id"].eq("CMC:2"), "cmc_id"] = 10
    with pytest.raises(XSMOMError, match="instrument_id"):
        build_xsmom_decision(panel, _spec(), DECISION)


def test_market_cap_band_is_inclusive_and_outside_fails_closed() -> None:
    panel = _panel(100)
    panel.loc[_latest_mask(panel, 1), "market_cap_usd"] = 10_000_000.0
    panel.loc[_latest_mask(panel, 2), "market_cap_usd"] = 1_000_000_000.0
    assert build_xsmom_decision(panel, _spec(), DECISION).status.startswith("TARGETS")

    panel.loc[_latest_mask(panel, 100), "market_cap_usd"] = 1_000_000_000.01
    assert build_xsmom_decision(panel, _spec(), DECISION).status == "NO_SIGNAL"


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("venue", "Bybit", "Binance"),
        ("market", "Perpetual", "Spot"),
        ("data_status", "INVALID", "VALID data_status"),
    ],
)
def test_every_contributing_bar_is_bound_to_binance_spot_valid(
    column: str,
    value: str,
    message: str,
) -> None:
    panel = _panel()
    panel.loc[0, column] = value
    with pytest.raises(XSMOMError, match=message):
        build_xsmom_decision(panel, _spec(), DECISION)


def test_venue_binding_is_causal_unique_and_has_nonempty_base() -> None:
    panel = _panel()
    panel.loc[0, "venue_symbol_bound_at_utc"] = "2024-01-02T00:00:01Z"
    with pytest.raises(XSMOMError, match="causally bound"):
        build_xsmom_decision(panel, _spec(), DECISION)

    collision = _panel()
    collision.loc[collision["instrument_id"].eq("CMC:2"), "venue_symbol"] = "A1USDT"
    with pytest.raises(XSMOMError, match="multiple stable identities"):
        build_xsmom_decision(collision, _spec(), DECISION)

    empty_base = _panel()
    empty_base.loc[empty_base["instrument_id"].eq("CMC:1"), "venue_symbol"] = "USDT"
    with pytest.raises(XSMOMError, match="non-empty"):
        build_xsmom_decision(empty_base, _spec(), DECISION)


def test_boolean_cmc_id_is_rejected_before_integer_coercion() -> None:
    panel = _panel()
    panel["cmc_id"] = panel["cmc_id"].astype(object)
    panel.loc[0, "cmc_id"] = True
    with pytest.raises(XSMOMError, match="not bool"):
        build_xsmom_decision(panel, _spec(), DECISION)


def test_public_target_and_decision_constructors_fail_closed() -> None:
    result = build_xsmom_decision(_panel(), _spec(), DECISION)
    target = result.candidate_targets[0]
    assert target.execution_status == "PENDING_EXECUTION_VALIDATION"

    with pytest.raises(XSMOMError, match="never authorize"):
        replace(target, real_money_authorized=True)
    with pytest.raises(XSMOMError, match="4.75"):
        replace(target, target_weight=9.99)
    with pytest.raises(XSMOMError, match="pending independent validation"):
        replace(target, execution_status="FILLED")
    with pytest.raises(XSMOMError, match="sealed to research outcomes"):
        replace(result, status="PASS")


@pytest.mark.parametrize("field", ["cohort_digest", "score_digest", "target_set_digest"])
def test_canonical_output_digests_detect_tampering(field: str) -> None:
    result = build_xsmom_decision(_panel(), _spec(), DECISION)
    with pytest.raises(XSMOMError, match="digest"):
        replace(result, **{field: "0" * 64})


def test_scores_are_bound_to_decision_spec_and_targets() -> None:
    result = build_xsmom_decision(_panel(), _spec(), DECISION)
    first = result.cohort_scores[0]
    changed = replace(first, liquidity_median_usd=first.liquidity_median_usd + 1.0)
    with pytest.raises(XSMOMError, match="digest"):
        replace(result, cohort_scores=(changed, *result.cohort_scores[1:]))

    tampered_target = replace(result.candidate_targets[0], momentum_return=999.0)
    with pytest.raises(XSMOMError, match="scores must match"):
        replace(result, candidate_targets=(tampered_target, *result.candidate_targets[1:]))


def test_public_outputs_reject_naive_or_non_utc_timestamps() -> None:
    result = build_xsmom_decision(_panel(), _spec(), DECISION)
    target = result.candidate_targets[0]
    with pytest.raises(XSMOMError, match="timezone-aware"):
        replace(target, decision_timestamp=target.decision_timestamp.tz_localize(None))
    with pytest.raises(XSMOMError, match="timezone-aware"):
        replace(result, expiration_timestamp=result.expiration_timestamp.tz_localize(None))

    mexico = result.decision_timestamp.tz_convert("America/Mexico_City")
    with pytest.raises(XSMOMError, match="UTC offset zero"):
        replace(result, decision_timestamp=mexico)


def test_decision_rejects_reordered_scores_even_with_recomputed_outputs() -> None:
    result = build_xsmom_decision(_panel(), _spec(), DECISION)
    swapped = (result.cohort_scores[1], result.cohort_scores[0], *result.cohort_scores[2:])
    with pytest.raises(XSMOMError, match="sealed liquidity/cmc_id order"):
        replace(result, cohort_scores=swapped)


def test_selected_score_cannot_hide_a_failed_min_notional_precheck() -> None:
    result = build_xsmom_decision(_panel(), _spec(), DECISION)
    selected = result.candidate_targets[0].instrument_id
    changed = tuple(
        replace(score, min_notional_precheck_passed=False)
        if score.instrument_id == selected
        else score
        for score in result.cohort_scores
    )
    with pytest.raises(XSMOMError, match="must pass min-notional precheck"):
        replace(result, cohort_scores=changed)


def test_invalid_classification_interval_end_is_not_treated_as_open_ended() -> None:
    panel = _panel()
    panel.loc[_latest_mask(panel, 1), "classification_valid_to_utc"] = "garbage"
    with pytest.raises(XSMOMError, match="valid timestamp or explicit null"):
        build_xsmom_decision(panel, _spec(), DECISION)
