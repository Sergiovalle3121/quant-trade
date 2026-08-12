from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from quant_trade.research.crypto_economic_evidence import (
    CryptoEconomicEvidenceError,
    canonical_evidence_digest,
    derive_capacity,
    derive_execution_economics,
    derive_overfitting_evidence,
    derive_pnl_concentration,
    derive_stress_evidence,
)
from quant_trade.research.crypto_evaluator import (
    EvaluationResult,
    ExecutionResult,
    RebalanceRecord,
)


def _execution(
    *,
    instrument_id: str = "CMC:2",
    side: str = "buy",
    requested_notional_usd: float = 100.0,
    filled_notional_usd: float = 100.0,
    filled_quantity: float = 10.0,
    open_price: float | None = 10.0,
    fill_price: float | None = 10.0,
    fee_usd: float = 1.0,
    impact_usd: float = 1.0,
    status: str = "FILLED",
    decision_timestamp: str = "2020-01-01 00:00:00",
    execution_timestamp: str | None = "2020-01-02 00:00:00",
) -> ExecutionResult:
    return ExecutionResult(
        decision_timestamp=decision_timestamp,
        execution_timestamp=execution_timestamp,
        instrument_id=instrument_id,
        order_intent="TARGET_PORTFOLIO",
        side=side,
        requested_quantity=(requested_notional_usd / open_price if open_price else 0.0),
        filled_quantity=filled_quantity,
        refused_quantity=0.0,
        requested_notional_usd=requested_notional_usd,
        filled_notional_usd=filled_notional_usd,
        open_price=open_price,
        fill_price=fill_price,
        fee_usd=fee_usd,
        impact_usd=impact_usd,
        status=status,
        reason="",
    )


def _result(
    *,
    final_value: float = 1_100.0,
    total_cost: float = 2.0,
    executions: list[ExecutionResult] | None = None,
    include_rebalance: bool = True,
) -> EvaluationResult:
    equity = pd.Series(
        [1_000.0, final_value],
        index=pd.to_datetime(["2020-01-01", "2020-01-03"]),
        dtype=float,
    )
    result = EvaluationResult(
        equity=equity,
        executions=[_execution()] if executions is None else executions,
        total_turnover=0.05,
        total_cost_usd=total_cost,
        initial_capital_usd=1_000.0,
    )
    if include_rebalance:
        result.rebalances.append(
            RebalanceRecord(
                decision_timestamp="2020-01-01 00:00:00",
                timestamp="2020-01-02 00:00:00",
                portfolio_value_usd=1_000.0,
                turnover=0.05,
                cost_usd=total_cost,
                names_targeted=1,
                names_held=1,
                refused_legs=0,
                capped_legs=0,
                unpriceable_legs=0,
            )
        )
    return result


def _assert_canonical_digest(evidence: dict[str, object]) -> None:
    json.dumps(evidence, allow_nan=False)
    payload = dict(evidence)
    digest = payload.pop("digest")
    assert digest == canonical_evidence_digest(payload)


def test_execution_economics_derives_gross_alpha_and_nearest_rank_p95() -> None:
    evidence = derive_execution_economics(
        _result(final_value=1_100.0),
        {
            "btc_buy_and_hold": _result(final_value=1_050.0),
            "eligible_equal_weight": _result(final_value=1_020.0),
        },
    )

    assert evidence["candidate"]["net_return"] == pytest.approx(0.10)
    assert evidence["candidate"]["gross_return"] == pytest.approx(0.102)
    assert evidence["best_gross_benchmark"] == "btc_buy_and_hold"
    assert evidence["gross_alpha_return"] == pytest.approx(0.05)
    profile = evidence["candidate"]["cost_profile"]
    assert profile["p95_rate"] == pytest.approx(0.02)
    assert profile["total_cost_p95_return"] == pytest.approx(0.002)
    _assert_canonical_digest(evidence)


def test_execution_economics_rejects_missing_benchmark_and_non_finite_data() -> None:
    with pytest.raises(CryptoEconomicEvidenceError, match="exactly"):
        derive_execution_economics(
            _result(),
            {"btc_buy_and_hold": _result()},
        )

    invalid = _result()
    invalid.equity.iloc[-1] = np.nan
    with pytest.raises(CryptoEconomicEvidenceError, match="finite"):
        derive_execution_economics(
            invalid,
            {
                "btc_buy_and_hold": _result(),
                "eligible_equal_weight": _result(),
            },
        )


def test_execution_economics_rejects_unmeasurable_costs() -> None:
    no_cost = _result(
        total_cost=0.0,
        executions=[_execution(fee_usd=0.0, impact_usd=0.0)],
    )
    with pytest.raises(CryptoEconomicEvidenceError, match="without measurable"):
        derive_execution_economics(
            no_cost,
            {
                "btc_buy_and_hold": _result(),
                "eligible_equal_weight": _result(),
            },
        )


def test_pnl_concentration_reconciles_embedded_impact_and_ignores_future_mark() -> None:
    # The fill embeds $1 of bar impact.  impact_usd reports that $1 plus $1 of
    # model impact, so cash cost is fee(1) + impact(2) - embedded(1) = $2.
    buy = _execution(
        filled_notional_usd=101.0,
        filled_quantity=10.0,
        open_price=10.0,
        fill_price=10.1,
        fee_usd=1.0,
        impact_usd=2.0,
    )
    result = _result(final_value=1_107.0, total_cost=2.0, executions=[buy])
    panel = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2020-01-03", "2020-01-04"]),
            "instrument_id": ["CMC:2", "CMC:2"],
            "mark_price": [21.0, 999.0],
            "data_status": ["VALID", "VALID"],
        }
    )

    evidence = derive_pnl_concentration(result, panel)

    assert evidence["asset_pnl_usd"] == {"CMC:2": pytest.approx(107.0)}
    assert evidence["final_marks_usd"] == {"CMC:2": 21.0}
    assert evidence["max_asset_positive_pnl_share"] == 1.0
    assert evidence["max_episode_positive_pnl_share"] == 1.0
    assert evidence["reconciliation_error_usd"] == pytest.approx(0.0)
    assert evidence["episodes"][0]["closure"] == "FINAL_CAUSAL_MARK"
    _assert_canonical_digest(evidence)


def test_pnl_concentration_handles_terminal_write_down_and_no_positive_pnl() -> None:
    buy = _execution(
        instrument_id="CMC:9",
        filled_notional_usd=100.0,
        filled_quantity=5.0,
        open_price=20.0,
        fill_price=20.0,
        fee_usd=1.0,
        impact_usd=0.0,
    )
    write_down = _execution(
        instrument_id="CMC:9",
        side="sell",
        requested_notional_usd=100.0,
        filled_notional_usd=0.0,
        filled_quantity=0.0,
        open_price=None,
        fill_price=None,
        fee_usd=0.0,
        impact_usd=0.0,
        status="WRITTEN_DOWN",
        decision_timestamp="2020-01-03 00:00:00",
        execution_timestamp="2020-01-03 00:00:00",
    )
    # A write-down removes requested_quantity.  The helper above derives it
    # from notional/open, so make the terminal quantity explicit.
    write_down = ExecutionResult(
        **{**write_down.to_dict(), "requested_quantity": 5.0, "refused_quantity": 5.0}
    )
    result = _result(final_value=899.0, total_cost=1.0, executions=[buy, write_down])
    panel = pd.DataFrame(columns=["timestamp", "instrument_id", "mark_price", "data_status"])

    evidence = derive_pnl_concentration(result, panel)

    assert evidence["asset_pnl_usd"] == {"CMC:9": pytest.approx(-101.0)}
    assert evidence["positive_asset_pnl_usd"] == 0.0
    assert evidence["positive_episode_pnl_usd"] == 0.0
    assert evidence["max_asset_positive_pnl_share"] == 0.0
    assert evidence["max_episode_positive_pnl_share"] == 0.0
    assert evidence["episodes"][0]["closure"] == "WRITTEN_DOWN"


def test_pnl_concentration_fails_when_attribution_cannot_reconcile() -> None:
    result = _result(
        final_value=1_108.0,
        total_cost=2.0,
        executions=[
            _execution(
                filled_notional_usd=101.0,
                open_price=10.0,
                fill_price=10.1,
                fee_usd=1.0,
                impact_usd=2.0,
            )
        ],
    )
    panel = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2020-01-03"]),
            "instrument_id": ["CMC:2"],
            "mark_price": [21.0],
        }
    )
    with pytest.raises(CryptoEconomicEvidenceError, match="does not reconcile"):
        derive_pnl_concentration(result, panel)


def test_capacity_uses_minimum_of_adv_and_depth_for_every_buy_leg() -> None:
    evidence = derive_capacity(
        _result(),
        {
            "CMC:2": SimpleNamespace(
                median_daily_notional_20d_usd=100_000.0,
                executable_depth_usd=10_000.0,
            )
        },
        500.0,
    )

    assert evidence["legs"][0]["order_limit_usd"] == 500.0
    assert evidence["legs"][0]["requested_nav_fraction"] == pytest.approx(0.1)
    assert evidence["capacity_usd"] == pytest.approx(5_000.0)
    assert evidence["capacity_multiple_of_canary"] == pytest.approx(10.0)
    _assert_canonical_digest(evidence)


@pytest.mark.parametrize("canary", [0.0, -1.0, 500.01, np.nan])
def test_capacity_rejects_invalid_canary(canary: float) -> None:
    with pytest.raises(CryptoEconomicEvidenceError, match="canary"):
        derive_capacity(
            _result(),
            {
                "CMC:2": {
                    "median_daily_notional_20d_usd": 100_000.0,
                    "executable_depth_usd": 10_000.0,
                }
            },
            canary,
        )


def test_capacity_rejects_missing_or_incomplete_limits() -> None:
    with pytest.raises(CryptoEconomicEvidenceError, match="missing"):
        derive_capacity(_result(), {}, 100.0)
    with pytest.raises(CryptoEconomicEvidenceError, match="executable_depth"):
        derive_capacity(
            _result(),
            {"CMC:2": {"median_daily_notional_20d_usd": 100_000.0}},
            100.0,
        )


def test_stress_evidence_binds_exact_profile_and_full_result_payload() -> None:
    stressed = _result()
    stressed.cost_multiplier = 2.0
    stressed.fill_fraction_multiplier = 0.5
    evidence = derive_stress_evidence(stressed, cost_multiplier=2.0, fill_fraction=0.5)

    assert evidence["stress_profile"] == {"cost_multiplier": 2.0, "fill_fraction": 0.5}
    assert evidence["total_return"] == pytest.approx(0.1)
    assert evidence["result_payload_digest"] == canonical_evidence_digest(
        evidence["result_payload"]
    )
    _assert_canonical_digest(evidence)


@pytest.mark.parametrize(
    ("cost_multiplier", "fill_fraction"),
    [(1.99, 0.5), (2.0, 0.49), (np.nan, 0.5), (2.0, np.nan)],
)
def test_stress_evidence_rejects_wrong_profiles(
    cost_multiplier: float, fill_fraction: float
) -> None:
    stressed = _result()
    stressed.cost_multiplier = 2.0
    stressed.fill_fraction_multiplier = 0.5
    with pytest.raises(CryptoEconomicEvidenceError):
        derive_stress_evidence(
            stressed,
            cost_multiplier=cost_multiplier,
            fill_fraction=fill_fraction,
        )


def test_stress_evidence_rejects_missing_execution_payload() -> None:
    result = _result(executions=[])
    result.cost_multiplier = 2.0
    result.fill_fraction_multiplier = 0.5
    with pytest.raises(CryptoEconomicEvidenceError, match="execution"):
        derive_stress_evidence(result)


def test_stress_evidence_rejects_an_unstressed_result_with_claimed_parameters() -> None:
    with pytest.raises(CryptoEconomicEvidenceError, match="not evaluated"):
        derive_stress_evidence(_result(), cost_multiplier=2.0, fill_fraction=0.5)


def _trial_returns(count: int = 15, observations: int = 40) -> dict[str, pd.Series]:
    index = pd.date_range("2019-01-01", periods=observations, freq="D")
    sample = np.arange(observations, dtype=float)
    trials: dict[str, pd.Series] = {}
    for trial in range(count):
        values = (
            np.sin((sample + trial * 0.37) / (2.3 + trial * 0.03)) * 0.01
            + ((sample + trial) % 7 - 3.0) * (trial + 1) * 0.00001
        )
        series = pd.Series(values, index=index, dtype=float)
        series.attrs["data_scope"] = "selection"
        trials[f"trial-{trial:02d}"] = series
    return trials


def test_overfitting_evidence_computes_cscv_and_four_walk_forward_windows() -> None:
    evidence = derive_overfitting_evidence(_trial_returns(), partitions=8, min_windows=4)

    assert evidence["trials"] == 15
    assert evidence["observations"] == 40
    assert 0.0 <= evidence["pbo"] <= 1.0
    assert evidence["cscv"]["combinations"] == 70
    assert evidence["windows"] == 4
    assert len(evidence["walk_forward_windows"]) == 4
    assert evidence["data_scope"] == "selection"
    _assert_canonical_digest(evidence)


def test_overfitting_evidence_rejects_fourteen_trials() -> None:
    with pytest.raises(CryptoEconomicEvidenceError, match="at least 15"):
        derive_overfitting_evidence(_trial_returns(count=14), partitions=8)


def test_overfitting_evidence_rejects_constant_nan_duplicate_and_unscoped_returns() -> None:
    constant = _trial_returns()
    constant["trial-00"] = pd.Series(np.ones(40), index=constant["trial-00"].index, dtype=float)
    constant["trial-00"].attrs["data_scope"] = "selection"
    with pytest.raises(CryptoEconomicEvidenceError, match="constant"):
        derive_overfitting_evidence(constant, partitions=8)

    non_finite = _trial_returns()
    non_finite["trial-00"].iloc[3] = np.nan
    with pytest.raises(CryptoEconomicEvidenceError, match="non-finite"):
        derive_overfitting_evidence(non_finite, partitions=8)

    duplicate = _trial_returns()
    copy = duplicate["trial-00"].copy()
    copy.attrs["data_scope"] = "selection"
    duplicate["trial-01"] = copy
    with pytest.raises(CryptoEconomicEvidenceError, match="duplicate"):
        derive_overfitting_evidence(duplicate, partitions=8)

    unscoped = _trial_returns()
    unscoped["trial-00"].attrs.clear()
    with pytest.raises(CryptoEconomicEvidenceError, match="data_scope"):
        derive_overfitting_evidence(unscoped, partitions=8)


def test_overfitting_evidence_rejects_unaligned_and_insufficient_samples() -> None:
    unaligned = _trial_returns()
    shifted = unaligned["trial-00"].copy()
    shifted.index = shifted.index + pd.Timedelta(days=1)
    shifted.attrs["data_scope"] = "selection"
    unaligned["trial-00"] = shifted
    with pytest.raises(CryptoEconomicEvidenceError, match="aligned"):
        derive_overfitting_evidence(unaligned, partitions=8)

    with pytest.raises(CryptoEconomicEvidenceError, match="at least"):
        derive_overfitting_evidence(_trial_returns(observations=8), partitions=4)
