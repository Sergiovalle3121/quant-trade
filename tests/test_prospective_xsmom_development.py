from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pandas as pd
import pytest

from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_bytes
from quant_trade.research.prospective_xsmom import load_xsmom_spec
from quant_trade.research.prospective_xsmom_development import (
    ARTIFACT_FILES,
    REAL_ARTIFACT_KIND,
    SYNTHETIC_ARTIFACT_KIND,
    XSMOMDevelopmentExecution,
    XSMOMDevelopmentPerformance,
    XSMOMDevelopmentScenario,
    XSMOMDevelopmentVerdict,
    evaluate_xsmom_development,
)

CONFIG = Path("configs/experiments/binance_liquid_xsmom_30d_top20_weekly_v1.yaml")
DECISION_START = pd.Timestamp("2022-02-03T00:00:00Z")
DECISION_END = pd.Timestamp("2022-03-24T00:00:00Z")
EVIDENCE_END = pd.Timestamp("2022-04-02T00:00:00Z")
HOLDOUT_START = pd.Timestamp("2023-11-29T00:00:00Z")


def _spec():
    return load_xsmom_spec(CONFIG)


def _utc_text(value: pd.Timestamp) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _selection_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    days = pd.date_range(
        DECISION_START - pd.Timedelta(days=31),
        DECISION_END - pd.Timedelta(days=1),
        freq="D",
        tz="UTC",
    )
    for cmc_id in range(1, 102):
        for offset, day in enumerate(days):
            close = 100.0 * (1.0 + cmc_id / 20_000.0 * offset)
            rows.append(
                {
                    "instrument_id": f"CMC:{cmc_id}",
                    "cmc_id": cmc_id,
                    "venue_symbol": "BTCUSDT" if cmc_id == 1 else f"A{cmc_id}USDT",
                    "venue": "Binance",
                    "market": "Spot",
                    "data_status": "VALID",
                    "timestamp": _utc_text(day),
                    "bar_closed_at_utc": _utc_text(day + pd.Timedelta(days=1)),
                    "venue_symbol_bound_at_utc": "2020-01-01T00:00:00Z",
                    "universe_observed_at_utc": _utc_text(day + pd.Timedelta(days=1)),
                    "classification_public_known_at_utc": "2020-01-01T00:00:00Z",
                    "classification_valid_from_utc": "2020-01-01T00:00:00Z",
                    "classification_valid_to_utc": None,
                    "symbol_rules_observed_at_utc": "2020-01-01T00:00:00Z",
                    "close": close,
                    "venue_turnover_usd": 30_000_000.0 - cmc_id * 10_000.0,
                    "market_cap_usd": 100_000_000.0,
                    "eligible_to_open": True,
                    "tradable": True,
                    "is_stablecoin": False,
                    "is_wrapped_asset": False,
                    "is_leveraged_token": False,
                    "is_derivative_token": False,
                    "is_rebase_token": False,
                    "min_notional_usd": 1.0,
                }
            )
    return rows


def _price(cmc_id: int, timestamp: pd.Timestamp) -> float:
    elapsed = (timestamp - (DECISION_START - pd.Timedelta(days=31))).days
    return 100.0 * (1.0 + cmc_id / 20_000.0 * elapsed)


def _execution_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    fridays = pd.date_range(
        DECISION_START + pd.Timedelta(days=1),
        DECISION_END + pd.Timedelta(days=8),
        freq="7D",
        tz="UTC",
    )
    for friday in fridays:
        for cmc_id in range(1, 102):
            open_price = _price(cmc_id, friday)
            rows.append(
                {
                    "timestamp": _utc_text(friday),
                    "bar_closed_at_utc": _utc_text(friday + pd.Timedelta(days=1)),
                    "instrument_id": f"CMC:{cmc_id}",
                    "cmc_id": cmc_id,
                    "venue_symbol": "BTCUSDT" if cmc_id == 1 else f"A{cmc_id}USDT",
                    "venue": "Binance",
                    "market": "Spot",
                    "open": open_price,
                    "open_observed_at_utc": _utc_text(friday),
                    "mark_price": _price(cmc_id, friday + pd.Timedelta(days=1)),
                    "mark_observed_at_utc": _utc_text(friday + pd.Timedelta(days=1)),
                    "data_status": "VALID",
                    "tradable": True,
                    "market_event": "NONE",
                    "market_event_observed_at_utc": None,
                }
            )
    return rows


def _term_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    fridays = pd.date_range(
        DECISION_START + pd.Timedelta(days=1),
        DECISION_END + pd.Timedelta(days=1),
        freq="7D",
        tz="UTC",
    )
    for friday in fridays:
        observed = friday - pd.Timedelta(days=1)
        for cmc_id in range(1, 102):
            rows.append(
                {
                    "execution_timestamp_utc": _utc_text(friday),
                    "instrument_id": f"CMC:{cmc_id}",
                    "cmc_id": cmc_id,
                    "venue_symbol": "BTCUSDT" if cmc_id == 1 else f"A{cmc_id}USDT",
                    "venue": "Binance",
                    "market": "Spot",
                    "observed_at_utc": _utc_text(observed),
                    "fee_observed_at_utc": _utc_text(observed),
                    "valid_from_utc": "2020-01-01T00:00:00Z",
                    "valid_to_utc": None,
                    "cost_sample_end_utc": _utc_text(observed),
                    "tick_size": 0.00000001,
                    "quantity_step": 0.00000001,
                    "min_quantity": 0.00000001,
                    "max_quantity": 1_000_000_000.0,
                    "min_notional_quote_usdt": 1.0,
                    "max_notional_quote_usdt": None,
                    "taker_fee_bps": 10.0,
                    "spread_cost_bps_p75": 5.0,
                    "impact_cost_bps_p75": 5.0,
                    "rules_source_sha256": "a" * 64,
                    "fee_source_sha256": "b" * 64,
                    "cost_source_sha256": "c" * 64,
                }
            )
    return rows


def _jsonl(rows: list[dict[str, Any]]) -> bytes:
    return ("".join(canonical_dumps(row) + "\n" for row in rows)).encode("utf-8")


def _write_bundle(
    root: Path,
    *,
    artifact_kind: str = SYNTHETIC_ARTIFACT_KIND,
    selection_rows: list[dict[str, Any]] | None = None,
    execution_rows: list[dict[str, Any]] | None = None,
    term_rows: list[dict[str, Any]] | None = None,
    write_artifacts: bool = True,
) -> dict[str, Any]:
    payload_rows = {
        "selection_panel.jsonl": selection_rows or _selection_rows(),
        "execution_bars.jsonl": execution_rows or _execution_rows(),
        "execution_terms.jsonl": term_rows or _term_rows(),
    }
    payloads = {name: _jsonl(rows) for name, rows in payload_rows.items()}
    if write_artifacts:
        for name, payload in payloads.items():
            (root / name).write_bytes(payload)
    manifest = {
        "schema_version": 1,
        "artifact_kind": artifact_kind,
        "strategy_id": "binance_liquid_xsmom_30d_top20_weekly_v1",
        "strategy_spec_seal": _spec().seal(),
        "venue": "Binance",
        "market": "Spot",
        "decision_start_utc": _utc_text(DECISION_START),
        "decision_end_utc": _utc_text(DECISION_END),
        "evidence_end_utc": _utc_text(EVIDENCE_END),
        "holdout_start_utc": _utc_text(HOLDOUT_START),
        "contains_holdout_data": False,
        "causal_verification_status": "VERIFIED_CAUSAL",
        "evaluator_network_access_required": False,
        "independent_preregistration_commit_sha": "1" * 40,
        "builder_commit_sha": "2" * 40,
        "file_sha256": {name: sha256_of_bytes(payload) for name, payload in payloads.items()},
        "row_counts": {name: len(rows) for name, rows in payload_rows.items()},
        "source_artifact_sha256": {
            "identity_and_classification": "d" * 64,
            "binance_daily_bars": "e" * 64,
            "binance_symbol_rules": "f" * 64,
            "binance_account_fees": "b" * 64,
            "symbol_cost_model": "c" * 64,
        },
    }
    (root / "manifest.json").write_bytes((canonical_dumps(manifest) + "\n").encode("utf-8"))
    return manifest


@pytest.fixture(scope="module")
def evaluated_bundle(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Path, XSMOMDevelopmentVerdict]:
    root = tmp_path_factory.mktemp("xsmom-development")
    _write_bundle(root)
    return root, evaluate_xsmom_development(
        root,
        _spec(),
        allow_synthetic_test_artifact=True,
    )


def test_synthetic_contract_evaluation_is_reproducible_and_never_promotional(
    evaluated_bundle: tuple[Path, XSMOMDevelopmentVerdict],
) -> None:
    root, first = evaluated_bundle
    second = evaluate_xsmom_development(
        root,
        _spec(),
        allow_synthetic_test_artifact=True,
    )

    assert first.to_dict() == second.to_dict()
    assert first.report_sha256() == second.report_sha256()
    assert first.status in {"NO_GO", "INSUFFICIENT_EVIDENCE"}
    assert first.decision_count == first.completed_weekly_periods == 8
    assert len(first.cohort_digests) == 8
    assert set(first.scenarios) == {"normal", "stress_2x_costs_50pct_fills"}
    normal = first.scenarios["normal"]
    stress = first.scenarios["stress_2x_costs_50pct_fills"]
    assert normal.cost_multiplier == normal.fill_fraction == 1.0
    assert stress.cost_multiplier == 2.0
    assert stress.fill_fraction == 0.5
    assert set(normal.performance) == {
        "candidate_xsmom",
        "liquidity_control",
        "btc_95_cash_5",
        "btc_100",
    }
    assert set(normal.block_outperformance_counts) == {
        "liquidity_control",
        "btc_95_cash_5",
        "btc_100",
    }
    assert all(0 <= value <= 4 for value in normal.block_outperformance_counts.values())
    assert not first.promotion_authorized
    assert not first.live_execution_authorized
    assert not first.real_money_authorized
    assert "SYNTHETIC_TEST_DATA_IS_NOT_ECONOMIC_EVIDENCE" in first.reasons
    assert set(first.evidence_hashes).issuperset({"spec", "manifest.json", *ARTIFACT_FILES})


def test_every_simulated_fill_is_exact_next_friday_and_costs_are_symbol_specific(
    evaluated_bundle: tuple[Path, XSMOMDevelopmentVerdict],
) -> None:
    _, verdict = evaluated_bundle
    normal = verdict.scenarios["normal"]
    fills = [item for item in normal.executions if item.filled_quantity > 0]

    assert fills
    assert all(pd.Timestamp(item.execution_timestamp).dayofweek == 4 for item in fills)
    assert all(
        pd.Timestamp(item.execution_timestamp)
        == pd.Timestamp(item.decision_timestamp) + pd.Timedelta(days=1)
        for item in fills
    )
    assert all(snapshot.same_boundary_fill_count == 0 for snapshot in normal.performance.values())
    assert all(
        item.fee_quote_usdt >= 0 and item.adverse_price_cost_quote_usdt >= 0 for item in fills
    )
    assert all(snapshot.total_cost_quote_usdt > 0 for snapshot in normal.performance.values())


def test_missing_exact_friday_open_expires_without_retry(tmp_path: Path) -> None:
    execution = _execution_rows()
    execution = [
        row
        for row in execution
        if not (row["timestamp"] == "2022-02-04T00:00:00Z" and row["instrument_id"] == "CMC:100")
    ]
    _write_bundle(tmp_path, execution_rows=execution)

    verdict = evaluate_xsmom_development(
        tmp_path,
        _spec(),
        allow_synthetic_test_artifact=True,
    )

    assert verdict.status in {"NO_GO", "INSUFFICIENT_EVIDENCE"}
    normal = verdict.scenarios["normal"]
    expired = [
        item
        for item in normal.executions
        if item.instrument_id == "CMC:100"
        and item.execution_timestamp == "2022-02-04T00:00:00+00:00"
    ]
    assert any(item.status == "EXPIRED" for item in expired)
    assert any("NO_RETRY" in item.reason for item in expired)


def test_missing_symbol_specific_terms_fails_closed(tmp_path: Path) -> None:
    terms = _term_rows()
    terms = [
        row
        for row in terms
        if not (
            row["execution_timestamp_utc"] == "2022-02-04T00:00:00Z"
            and row["instrument_id"] == "CMC:100"
        )
    ]
    _write_bundle(tmp_path, term_rows=terms)

    verdict = evaluate_xsmom_development(
        tmp_path,
        _spec(),
        allow_synthetic_test_artifact=True,
    )

    assert verdict.status == "INSUFFICIENT_EVIDENCE"
    assert any("MISSING_SYMBOL_SPECIFIC_TERMS_FOR_CMC:100" in reason for reason in verdict.reasons)
    assert not verdict.scenarios


def test_future_known_cost_inputs_fail_before_economic_evaluation(tmp_path: Path) -> None:
    terms = _term_rows()
    terms[0]["cost_sample_end_utc"] = terms[0]["execution_timestamp_utc"]
    _write_bundle(tmp_path, term_rows=terms)

    verdict = evaluate_xsmom_development(
        tmp_path,
        _spec(),
        allow_synthetic_test_artifact=True,
    )

    assert verdict.status == "INSUFFICIENT_EVIDENCE"
    assert "TERMS_OR_COSTS_WERE_NOT_KNOWN_BY_THURSDAY" in verdict.reasons
    assert not verdict.scenarios


def test_real_artifact_is_blocked_by_sealed_spec_before_market_files_open(
    tmp_path: Path,
) -> None:
    _write_bundle(tmp_path, artifact_kind=REAL_ARTIFACT_KIND, write_artifacts=False)

    verdict = evaluate_xsmom_development(tmp_path, _spec())

    assert verdict.status == "INSUFFICIENT_EVIDENCE"
    assert "SEALED_SPEC_DEVELOPMENT_WINDOW_NOT_ACTIVATED" in verdict.reasons
    assert "SEALED_SPEC_ECONOMIC_EVALUATION_FORBIDDEN" in verdict.reasons
    assert "SEALED_SPEC_STABLECOIN_POINT_IN_TIME_EVIDENCE_UNKNOWN" in verdict.reasons
    assert "POINT_IN_TIME_USDT_USD_CONVERSION_NOT_IMPLEMENTED" in verdict.reasons
    assert "SELECTION_PANEL.JSONL_MISSING_OR_UNREADABLE" not in verdict.reasons
    assert set(verdict.evidence_hashes) == {"spec", "manifest.json"}


def test_synthetic_artifact_requires_explicit_test_mode(tmp_path: Path) -> None:
    _write_bundle(tmp_path, write_artifacts=False)

    verdict = evaluate_xsmom_development(tmp_path, _spec())

    assert verdict.status == "INSUFFICIENT_EVIDENCE"
    assert "SYNTHETIC_ARTIFACT_REQUIRES_EXPLICIT_TEST_MODE" in verdict.reasons
    assert set(verdict.evidence_hashes) == {"spec", "manifest.json"}


def test_file_tamper_is_detected_before_parse(tmp_path: Path) -> None:
    _write_bundle(tmp_path)
    with (tmp_path / "selection_panel.jsonl").open("ab") as handle:
        handle.write(b"{}\n")

    verdict = evaluate_xsmom_development(
        tmp_path,
        _spec(),
        allow_synthetic_test_artifact=True,
    )

    assert verdict.status == "INSUFFICIENT_EVIDENCE"
    assert "SELECTION_PANEL.JSONL_SHA256_MISMATCH" in verdict.reasons


def test_verdict_type_cannot_pass_or_authorize_money() -> None:
    with pytest.raises(ValueError, match="never be PASS"):
        XSMOMDevelopmentVerdict(
            status="PASS",  # type: ignore[arg-type]
            strategy_id="binance_liquid_xsmom_30d_top20_weekly_v1",
            evidence_hashes={},
            decision_count=0,
            completed_weekly_periods=0,
            cohort_digests=(),
            scenarios={},
            reasons=("forbidden",),
        )

    base = XSMOMDevelopmentVerdict(
        status="INSUFFICIENT_EVIDENCE",
        strategy_id="binance_liquid_xsmom_30d_top20_weekly_v1",
        evidence_hashes={},
        decision_count=0,
        completed_weekly_periods=0,
        cohort_digests=(),
        scenarios={},
        reasons=("research only",),
    )
    with pytest.raises(ValueError, match="cannot authorize"):
        replace(base, real_money_authorized=True)


def test_public_execution_constructor_rejects_malformed_or_noncausal_values(
    evaluated_bundle: tuple[Path, XSMOMDevelopmentVerdict],
) -> None:
    _, verdict = evaluated_bundle
    execution = next(
        item for item in verdict.scenarios["normal"].executions if item.status == "FILLED"
    )
    assert isinstance(execution, XSMOMDevelopmentExecution)

    invalid_changes: tuple[dict[str, Any], ...] = (
        {"portfolio": "invented"},
        {"decision_timestamp": "2022-02-03T00:00:00"},
        {"execution_timestamp": execution.decision_timestamp},
        {"instrument_id": "BTCUSDT"},
        {"venue_symbol": "USDT"},
        {"side": "short"},
        {"status": "PASS"},
        {"requested_quantity": True},
        {"filled_quantity": float("nan")},
        {"refused_quantity": -1.0},
        {"open_price": float("inf")},
        {"fee_quote_usdt": -0.01},
        {"reason": " hidden\nreason"},
        {"status": "REFUSED", "reason": "rejected"},
    )
    for changes in invalid_changes:
        with pytest.raises(ValueError):
            replace(execution, **changes)


def test_public_performance_constructor_rejects_nan_bool_counts_and_inconsistent_equity(
    evaluated_bundle: tuple[Path, XSMOMDevelopmentVerdict],
) -> None:
    _, verdict = evaluated_bundle
    performance = verdict.scenarios["normal"].performance["candidate_xsmom"]
    assert isinstance(performance, XSMOMDevelopmentPerformance)

    invalid_changes: tuple[dict[str, Any], ...] = (
        {"initial_equity_quote_usdt": 0.0},
        {"terminal_equity_quote_usdt": float("nan")},
        {"total_return": performance.total_return + 0.01},
        {"annualized_weekly_sharpe": float("inf")},
        {"max_drawdown": -1.01},
        {"max_drawdown": 0.01},
        {"total_cost_quote_usdt": -0.01},
        {"execution_count": True},
        {"filled_count": -1},
        {"partial_count": performance.execution_count + 1},
    )
    for changes in invalid_changes:
        with pytest.raises(ValueError):
            replace(performance, **changes)


def test_public_scenario_constructor_requires_exact_typed_books_blocks_and_executions(
    evaluated_bundle: tuple[Path, XSMOMDevelopmentVerdict],
) -> None:
    _, verdict = evaluated_bundle
    scenario = verdict.scenarios["normal"]
    assert isinstance(scenario, XSMOMDevelopmentScenario)

    bad_performance = dict(scenario.performance)
    bad_performance.pop("btc_100")
    with pytest.raises(ValueError, match="exact four"):
        replace(scenario, performance=bad_performance)

    untyped_performance: dict[str, Any] = dict(scenario.performance)
    untyped_performance["btc_100"] = {"total_return": 0.0}
    with pytest.raises(ValueError, match="typed snapshots"):
        replace(scenario, performance=untyped_performance)

    for pair in ((2.0, 1.0), (1.0, 0.5), (True, 1.0), (float("nan"), 1.0)):
        with pytest.raises(ValueError):
            replace(scenario, cost_multiplier=pair[0], fill_fraction=pair[1])

    for block_value in (True, -1, 5):
        blocks = dict(scenario.block_outperformance_counts)
        blocks["btc_100"] = block_value
        with pytest.raises(ValueError):
            replace(scenario, block_outperformance_counts=blocks)
    missing_block = dict(scenario.block_outperformance_counts)
    missing_block.pop("btc_100")
    with pytest.raises(ValueError, match="exact three"):
        replace(scenario, block_outperformance_counts=missing_block)

    with pytest.raises(ValueError, match="tuple of typed"):
        replace(scenario, executions=list(scenario.executions))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="tuple of typed"):
        replace(scenario, executions=(*scenario.executions, "fake"))  # type: ignore[arg-type]

    performance = dict(scenario.performance)
    candidate = performance["candidate_xsmom"]
    performance["candidate_xsmom"] = replace(
        candidate,
        execution_count=candidate.execution_count + 1,
    )
    with pytest.raises(ValueError, match="counts disagree"):
        replace(scenario, performance=performance)

    performance = dict(scenario.performance)
    performance["candidate_xsmom"] = replace(
        candidate,
        total_cost_quote_usdt=candidate.total_cost_quote_usdt + 1.0,
    )
    with pytest.raises(ValueError, match="cost disagrees"):
        replace(scenario, performance=performance)


def test_public_verdict_constructor_requires_exact_sealed_envelope(
    evaluated_bundle: tuple[Path, XSMOMDevelopmentVerdict],
) -> None:
    _, verdict = evaluated_bundle

    invalid_changes: tuple[dict[str, Any], ...] = (
        {"schema_version": True},
        {"schema_version": 2},
        {"strategy_id": "another_strategy"},
        {"development_only": False},
        {"promotion_authorized": 1},
        {"live_execution_authorized": True},
        {"decision_count": True},
        {"completed_weekly_periods": -1},
        {"evidence_hashes": {"spec": "BAD"}},
        {"cohort_digests": ("0" * 63,) * verdict.decision_count},
        {"reasons": (" ",)},
        {"reasons": ("duplicate", "duplicate")},
        {"reasons": ("two\nlines",)},
    )
    for changes in invalid_changes:
        with pytest.raises(ValueError):
            replace(verdict, **changes)

    with pytest.raises(ValueError, match="exact normal and stress"):
        replace(verdict, scenarios={"normal": verdict.scenarios["normal"]})
    with pytest.raises(ValueError, match="typed XSMOM"):
        replace(
            verdict,
            scenarios={
                "normal": verdict.scenarios["normal"],
                "stress_2x_costs_50pct_fills": cast(Any, object()),
            },
        )
    with pytest.raises(ValueError, match="scenario names"):
        replace(
            verdict,
            scenarios={
                "normal": verdict.scenarios["stress_2x_costs_50pct_fills"],
                "stress_2x_costs_50pct_fills": verdict.scenarios["normal"],
            },
        )


def test_synthetic_prices_are_finite_and_monotonic_fixture_sanity() -> None:
    values = [
        _price(100, timestamp)
        for timestamp in pd.date_range("2022-02-04", periods=9, freq="7D", tz="UTC")
    ]
    assert all(math.isfinite(value) for value in values)
    assert values == sorted(values)
