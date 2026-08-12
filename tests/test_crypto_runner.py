from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

import quant_trade.research.runtime_provenance as runtime_provenance_module
from quant_trade.costs.crypto_lowcap import (
    DEFAULT_TIER_PROFILES,
    CostInput,
    TierCostProfile,
)
from quant_trade.data.crypto_manifest import (
    CausalValidationEvidence,
    CryptoDatasetManifest,
    CryptoManifestError,
    component_hashes,
)
from quant_trade.data.crypto_market_events import (
    MarketEventEvidence,
    MarketEventLedger,
)
from quant_trade.ops.crypto_gates import (
    CryptoGateError,
    Gate0Evidence,
    VenuePolicy,
    evaluate_gate0,
)
from quant_trade.research.crypto_evaluator import ExecutionLimits
from quant_trade.research.crypto_governance import (
    HYPOTHESIS_TRIAL_BUDGETS,
    CryptoGovernanceError,
    ExperimentSpec,
    evaluation_artifact_digest,
)
from quant_trade.research.crypto_runner import (
    RevealedHoldoutContext,
    SelectionContext,
    canonical_market_event_ledger_bytes,
    canonical_market_event_ledger_digest,
    canonical_panel_bytes,
    canonical_panel_digest,
    cohort_members_digest,
    cost_profiles_digest,
    execution_limits_digest,
    taker_fees_digest,
)
from quant_trade.research.crypto_runner import (
    run_protected_crypto_evaluation as _run_protected_crypto_evaluation,
)
from quant_trade.research.crypto_runner import (
    run_protected_crypto_selection as _run_protected_crypto_selection,
)
from quant_trade.research.holdout_seal import (
    HoldoutSeal,
    load_crypto_holdout_authorization,
    record_reveal,
    seal_crypto_holdout,
)
from quant_trade.research.runtime_provenance import RuntimeCodeProvenance

_EVENT_SOURCE_BYTES = b'{"source":"synthetic Bybit market-event notice"}'
_EVENT_SOURCE_SHA256 = hashlib.sha256(_EVENT_SOURCE_BYTES).hexdigest()
_PROFILES_BY_ROOT: dict[Path, tuple[TierCostProfile, ...]] = {}


class _TrustedRuntimeProvider:
    def inspect(self) -> RuntimeCodeProvenance:
        return RuntimeCodeProvenance(
            code_commit="a" * 40,
            source_mode="git-checkout",
            source_tree_digest="b" * 40,
            clean=True,
            source_root=str(Path.cwd().resolve()),
        )


@pytest.fixture(autouse=True)
def _trusted_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime_provenance_module, "_PROVIDER", _TrustedRuntimeProvider())


def run_protected_crypto_evaluation(**kwargs: Any):
    """Exercise the production API with the fixture's explicit source-bound profiles."""

    root = Path(kwargs["provenance_root"]).resolve()
    kwargs.setdefault("profiles", _PROFILES_BY_ROOT[root])
    return _run_protected_crypto_evaluation(**kwargs)


def run_protected_crypto_selection(**kwargs: Any):
    """Exercise the production API with the fixture's explicit source-bound profiles."""

    root = Path(kwargs["provenance_root"]).resolve()
    kwargs.setdefault("profiles", _PROFILES_BY_ROOT[root])
    return _run_protected_crypto_selection(**kwargs)


def _panel(start: str = "2024-01-01") -> pd.DataFrame:
    rows = []
    for day_index, day in enumerate(pd.date_range(start, periods=4, tz="UTC")):
        for symbol, base, cap, rank in (
            ("CMC:1", 40_000.0, 2_000_000_000.0, 1),
            ("CMC:2", 10.0, 100_000_000.0, 50),
        ):
            price = base * (1.0 + 0.02 * day_index)
            rows.append(
                {
                    "timestamp": day,
                    "symbol": symbol,
                    "venue": "bybit",
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "mark_price": price,
                    "volume": 1_000_000.0,
                    "venue_turnover_usd": 10_000_000.0,
                    "market_cap_usd": cap,
                    "cmc_rank": rank,
                    "eligible_to_open": symbol != "CMC:1",
                    "tradable": True,
                    "data_status": "VALID",
                    "market_event": "NONE",
                }
            )
    return pd.DataFrame(rows)


def _gate0_evidence() -> Gate0Evidence:
    return Gate0Evidence(
        venue="bybit",
        environment="demo",
        kyc_mexico_approved=True,
        contractual_entity_identified=True,
        spot_account_enabled=True,
        api_access_enabled=True,
        dedicated_subaccount_active=True,
        ip_allowlist_active=True,
        read_permission_enabled=True,
        spot_permission_enabled=True,
        withdrawal_permission_disabled=True,
        transfer_permission_disabled=True,
        margin_permission_disabled=True,
        derivatives_permission_disabled=True,
        loan_permission_disabled=True,
        fee_rate_captured_per_symbol=True,
        minimum_deposit_test_passed=True,
        minimum_withdrawal_test_passed=True,
        dataset_venue="bybit",
        cost_venue="bybit",
        planned_execution_venue="bybit",
    )


def _market_event(
    *,
    timestamp: str,
    event: str,
    recovery: float | None = None,
) -> MarketEventEvidence:
    return MarketEventEvidence(
        instrument_id="CMC:2",
        venue="bybit",
        event=event,
        effective_at_utc=timestamp,
        observed_at_utc=timestamp,
        source=f"Bybit event evidence: {event}",
        source_sha256=_EVENT_SOURCE_SHA256,
        terminal_recovery_price=recovery,
    )


def _manifest(
    provenance_root: Path,
    selection_panel: pd.DataFrame,
    holdout_panel: pd.DataFrame,
    selection_market_events: MarketEventLedger,
    holdout_market_events: MarketEventLedger,
    evidence_sources: dict[str, bytes],
) -> CryptoDatasetManifest:
    provenance_root.mkdir(parents=True)
    selection_component = provenance_root / "selection.panel.json"
    holdout_component = provenance_root / "holdout.panel.json"
    selection_events_component = provenance_root / "selection.market-events.json"
    holdout_events_component = provenance_root / "holdout.market-events.json"
    selection_component.write_bytes(canonical_panel_bytes(selection_panel))
    holdout_component.write_bytes(canonical_panel_bytes(holdout_panel))
    selection_events_component.write_bytes(
        canonical_market_event_ledger_bytes(selection_market_events)
    )
    holdout_events_component.write_bytes(canonical_market_event_ledger_bytes(holdout_market_events))
    source_paths: dict[str, Path] = {}
    for name, content in sorted(evidence_sources.items()):
        path = provenance_root / "evidence" / f"{hashlib.sha256(content).hexdigest()}.bin"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        source_paths[name] = path
    component_paths = {
        "selection_panel": selection_component,
        "holdout_panel": holdout_component,
        "selection_market_events": selection_events_component,
        "holdout_market_events": holdout_events_component,
        **source_paths,
    }
    return CryptoDatasetManifest(
        dataset_id="bybit-causal-panel-v2",
        status="TRUSTED_CAUSAL",
        venue="bybit",
        market="spot",
        quote_asset="USDT",
        timezone="UTC",
        start_date="2017-08-17",
        end_date="2024-01-04",
        rows=8,
        instruments=2,
        schema_version=2,
        code_commit="a" * 40,
        policy={
            "single_venue": True,
            "selection_panel_component": "selection_panel",
            "holdout_panel_component": "holdout_panel",
            "selection_market_events_component": "selection_market_events",
            "holdout_market_events_component": "holdout_market_events",
        },
        components=component_hashes(component_paths),
        component_provenance={
            "selection_panel": "selection.panel.json",
            "holdout_panel": "holdout.panel.json",
            "selection_market_events": "selection.market-events.json",
            "holdout_market_events": "holdout.market-events.json",
            **{
                name: path.relative_to(provenance_root).as_posix()
                for name, path in source_paths.items()
            },
        },
        causal_validation=CausalValidationEvidence(
            prefix_invariance_passed=True,
            fixed_venue_passed=True,
            stable_identity_and_rename_passed=True,
            unique_and_ambiguous_price_binding_passed=True,
            causal_warmup_passed=True,
            rank_exit_reentry_passed=True,
            gap_and_halt_semantics_passed=True,
            explicit_delisting_semantics_passed=True,
        ),
        gap_summary={"unexplained": 0},
        terms_status="research-only",
    )


def _criteria() -> dict[str, object]:
    return {
        "min_psr": 0.95,
        "min_dsr": 0.95,
        "max_pbo": 0.10,
        "min_walk_forward_windows": 4,
        "min_independent_trades": 30,
        "max_oos_drawdown": 0.25,
        "min_gross_alpha_cost_multiple": 2.0,
        "max_positive_pnl_share": 0.25,
        "min_capacity_canary_multiple": 2.0,
        "require_nonnegative_double_cost_half_fill": True,
        "canary_capital_usd": 500.0,
        "independent_trade_definition": "closed_nonoverlapping_portfolio_round_trip_v1",
    }


def _setup(
    tmp_path: Path,
    *,
    revealed: bool = True,
    selection_market_events: MarketEventLedger | None = None,
    holdout_market_events: MarketEventLedger | None = None,
    holdout_panel_market_event: str | None = None,
    holdout_panel_recovery: float | None = None,
    delisting_recovery: float = 0.0,
) -> tuple[
    CryptoDatasetManifest,
    Path,
    object,
    ExperimentSpec,
    RevealedHoldoutContext,
    dict[str, ExecutionLimits],
    dict[str, CostInput],
]:
    provenance_root = tmp_path / "provenance"
    holdout_panel = _panel()
    if holdout_panel_market_event is not None:
        event_row = holdout_panel["timestamp"].eq(pd.Timestamp("2024-01-04", tz="UTC")) & (
            holdout_panel["symbol"].eq("CMC:2")
        )
        holdout_panel.loc[event_row, "market_event"] = holdout_panel_market_event
        if holdout_panel_recovery is not None:
            holdout_panel["terminal_recovery_price"] = pd.Series(
                [None] * len(holdout_panel),
                dtype=object,
            )
            holdout_panel.loc[event_row, "terminal_recovery_price"] = holdout_panel_recovery
    selection_panel = _panel("2023-01-01")
    selection_events = selection_market_events or MarketEventLedger.from_events(())
    holdout_events = holdout_market_events or MarketEventLedger.from_events(())
    fee_source_bytes = {
        symbol: f'{{"endpoint":"/v5/account/fee-rate","symbol":"{symbol}"}}'.encode()
        for symbol in ("CMC:1", "CMC:2")
    }
    profile_source_bytes = b'{"fixture":"synthetic p75 order-book calibration"}'
    profile_source_sha256 = hashlib.sha256(profile_source_bytes).hexdigest()
    profiles = tuple(
        replace(
            profile,
            source="synthetic p75 order-book calibration fixture",
            captured_at_utc="2023-12-30T00:00:00Z",
            manifest_sha256=profile_source_sha256,
        )
        for profile in DEFAULT_TIER_PROFILES
    )
    evidence_sources = {
        **{
            f"fee_source_{symbol.replace(':', '_').lower()}": content
            for symbol, content in fee_source_bytes.items()
        },
        "cost_profile_source": profile_source_bytes,
        "market_event_source": _EVENT_SOURCE_BYTES,
    }
    manifest = _manifest(
        provenance_root,
        selection_panel,
        holdout_panel,
        selection_events,
        holdout_events,
        evidence_sources,
    )
    _PROFILES_BY_ROOT[provenance_root.resolve()] = profiles
    gate0 = evaluate_gate0(VenuePolicy(), _gate0_evidence())
    cohort = ["CMC:2"]
    limits = {
        symbol: ExecutionLimits(
            tick_size=0.01,
            quantity_step=0.001,
            min_notional_usd=1.0,
            median_daily_notional_20d_usd=10_000_000.0,
            executable_depth_usd=100_000.0,
        )
        for symbol in ("CMC:1", "CMC:2")
    }
    fees = {
        symbol: CostInput(
            name=f"{symbol}_account_taker_fee",
            value_bps=10.0,
            evidence_class="REAL_ACCOUNT_SPECIFIC",
            source="Bybit /v5/account/fee-rate",
            captured_at_utc="2023-12-30T00:00:00Z",
            raw_sha256=hashlib.sha256(fee_source_bytes[symbol]).hexdigest(),
            venue="bybit",
            endpoint="/v5/account/fee-rate",
            account_scope="dedicated-demo-subaccount",
            venue_symbol=symbol,
        )
        for symbol in ("CMC:1", "CMC:2")
    }
    seal = HoldoutSeal(
        seal_id="crypto-holdout-v1",
        dataset_id=manifest.dataset_id,
        dataset_digest=manifest.digest(),
        selection_start="2023-01-01",
        selection_end="2023-01-04",
        holdout_start="2024-01-01",
        holdout_end="2024-01-04",
        rationale="one final untouched evaluation",
        sealed_at_utc="2023-12-31T00:00:00Z",
        sealed_at_commit="a" * 40,
    )
    holdout_directory = tmp_path / "holdout"
    seal_crypto_holdout(
        holdout_directory,
        seal,
        manifest=manifest,
        provenance_root=provenance_root,
        manifest_digest=manifest.digest(),
        gate0_verdict=gate0,
        gate0_verdict_digest=gate0.digest(),
        gate0_evidence_digest=gate0.evidence_digest(),
    )
    authorization = load_crypto_holdout_authorization(holdout_directory)
    spec = ExperimentSpec(
        campaign_id="crypto-lowcap-2026-08",
        experiment_id="h1-capacity-v1",
        hypothesis_id="H1",
        hypothesis="capacity premium",
        strategy="crypto_capacity_illiquidity",
        strategy_params={
            "top_n": 1,
            "rebalance_frequency": "annual",
            "liquidity_window": 1,
        },
        control={"comparison_variable": "liquid_band", "liquid_band": True},
        refutation="non-positive net excess",
        dataset_id=manifest.dataset_id,
        dataset_digest=manifest.digest(),
        dataset_status="TRUSTED_CAUSAL",
        gate0_status="PASS",
        gate0_verdict_digest=gate0.digest(),
        gate0_evidence_digest=gate0.evidence_digest(),
        code_commit=manifest.code_commit,
        venue="bybit",
        venue_policy={
            "venue": "bybit",
            "venues": ["bybit"],
            "market": "spot",
            "environment": "demo",
            "fee_source": "operator_capture_per_symbol",
        },
        universe_policy={
            "market_cap_min_usd": 10_000_000,
            "market_cap_max_usd": 1_000_000_000,
            "quote": "USDT",
        },
        selection_start=seal.selection_start,
        selection_end=seal.selection_end,
        holdout_start=seal.holdout_start,
        holdout_end=seal.holdout_end,
        selection_panel_digest=canonical_panel_digest(selection_panel),
        holdout_panel_digest=canonical_panel_digest(holdout_panel),
        holdout_seal_digest=seal.seal(),
        holdout_authorization_digest=authorization.digest(),
        cohort_digest=cohort_members_digest(cohort),
        split_policy={
            "type": "sealed_date_holdout",
            "embargo_bars": 1,
            "panel_component_encoding": "canonical_panel_v1",
            "selection_panel_component": "selection_panel",
            "holdout_panel_component": "holdout_panel",
            "selection_market_events_component": "selection_market_events",
            "holdout_market_events_component": "holdout_market_events",
        },
        walk_forward_policy={
            "min_windows": 4,
            "selection_only": True,
            "cscv_partitions": 4,
        },
        benchmarks=[
            {
                "benchmark_id": "btc_buy_and_hold",
                "instrument_id": "CMC:1",
                "min_bound_bars": 1,
            },
            {
                "benchmark_id": "eligible_equal_weight",
                "top_n": 1,
                "rebalance_frequency": "annual",
            },
        ],
        execution_policy={
            "decision_to_execution_bars": 1,
            "execution_price": "open",
            "partial_fills": True,
            "execution_limits_digest": execution_limits_digest(limits),
        },
        cost_policy={
            "quantile": "p75",
            "fee_source": "operator_capture_per_symbol",
            "taker_fees_digest": taker_fees_digest(fees),
            "cost_profiles_digest": cost_profiles_digest(profiles),
            "initial_capital_usd": 1_000.0,
            "min_executable_fraction": 1.0,
            "delisting_recovery": delisting_recovery,
        },
        selection_criteria=_criteria(),
        trial_budget=4,
        campaign_trial_budgets=dict(HYPOTHESIS_TRIAL_BUDGETS),
        registered_at_utc="2023-12-31T00:00:00Z",
    )
    if revealed:
        record_reveal(
            holdout_directory,
            reason="single final evaluation",
            at_utc="2024-01-05T00:00:00Z",
            frozen_selection={"experiment_spec_seal": spec.seal()},
        )
    context = RevealedHoldoutContext(holdout_directory, holdout_panel, holdout_events)
    return manifest, provenance_root, gate0, spec, context, limits, fees


def test_canonical_panel_digest_preserves_sub_tenth_decimal_float_differences() -> None:
    first = _panel()
    second = _panel()
    first.loc[first.index[0], "venue_turnover_usd"] = 1.01e-11
    second.loc[second.index[0], "venue_turnover_usd"] = 4.99e-11

    assert canonical_panel_digest(first) != canonical_panel_digest(second)


def test_canonical_panel_digest_normalizes_signed_zero_and_timestamp_offsets() -> None:
    canonical = _panel()
    equivalent = canonical.copy()
    canonical.loc[canonical.index[0], "volume"] = 0.0
    equivalent.loc[equivalent.index[0], "volume"] = -0.0
    equivalent["timestamp"] = equivalent["timestamp"].map(
        lambda value: value.tz_convert("America/New_York").isoformat()
    )

    assert canonical_panel_bytes(canonical) == canonical_panel_bytes(equivalent)


def test_canonical_panel_payload_round_trips_without_changing_bytes() -> None:
    original = _panel()
    original.loc[original.index[0], "venue_turnover_usd"] = 1.2345678901234567
    encoded = canonical_panel_bytes(original)
    decoded = json.loads(encoded)
    reconstructed = pd.DataFrame(decoded["records"], columns=decoded["columns"])

    assert canonical_panel_bytes(reconstructed) == encoded
    assert canonical_panel_digest(reconstructed) == canonical_panel_digest(original)


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")])
def test_canonical_panel_digest_rejects_non_finite_floats(invalid: float) -> None:
    panel = _panel()
    panel.loc[panel.index[0], "close"] = invalid

    with pytest.raises(CryptoGovernanceError, match="NaN or an infinite"):
        canonical_panel_digest(panel)


def test_protected_runner_executes_candidate_and_both_benchmarks_with_bindings(
    tmp_path: Path,
) -> None:
    manifest, provenance_root, gate0, spec, context, limits, fees = _setup(tmp_path)
    run = run_protected_crypto_evaluation(
        manifest=manifest,
        provenance_root=provenance_root,
        gate0_verdict=gate0,  # type: ignore[arg-type]
        spec=spec,
        holdout=context,
        cohort_members=["CMC:2"],
        run_id="candidate-run",
        execution_limits=limits,
        taker_fees=fees,
    )
    assert set(run.benchmark_results) == {"btc_buy_and_hold", "eligible_equal_weight"}
    assert run.control_result is not None
    assert run.artifact["control_result_digest"]
    assert set(run.artifact["runs"]) == {
        "candidate",
        "control",
        "benchmarks",
        "stress_candidate",
    }
    assert (
        run.artifact["comparisons"]["sealed_control"]["artifact_digest"]
        == (run.artifact["control_result_digest"])
    )
    assert run.artifact_digest == evaluation_artifact_digest(run.artifact)
    assert run.artifact["holdout"]["test_range"] == ["2024-01-01", "2024-01-04"]
    assert run.artifact["policy_bindings"]["execution_policy_digest"] == (
        spec.execution_policy_digest
    )
    assert run.artifact["runtime_provenance"]["code_commit"] == spec.code_commit
    assert run.artifact["runtime_provenance"]["clean"] is True
    assert run.artifact["runtime_provenance"]["source_mode"] == "git-checkout"
    assert "source_root" not in run.artifact["runtime_provenance"]
    assert run.artifact["gate3_inputs"]["panel"]["digest"] == spec.holdout_panel_digest
    assert "payload" not in run.artifact["gate3_inputs"]["panel"]
    assert (
        run.artifact["gate3_inputs"]["panel"]["payload_omitted"] == "MARKET_DATA_LICENSE_UNRESOLVED"
    )
    assert (
        run.artifact["gate3_inputs"]["execution_limits"]["digest"]
        == (spec.execution_policy["execution_limits_digest"])
    )
    empty_events = MarketEventLedger.from_events(())
    assert run.artifact["market_events"] == empty_events.to_dict()
    assert run.artifact["market_events_component_digest"] == (
        canonical_market_event_ledger_digest(empty_events)
    )
    row = run.ledger_record()
    assert row["artifact_digest"] == run.artifact_digest
    assert row["test_sharpe_per_period"] == run.artifact["test_metrics"]["sharpe_per_period"]
    assert "preregistration_seal" not in row


def test_protected_runner_rejects_runtime_commit_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _WrongCommitProvider:
        def inspect(self) -> RuntimeCodeProvenance:
            return RuntimeCodeProvenance(
                code_commit="c" * 40,
                source_mode="git-checkout",
                source_tree_digest="d" * 40,
                clean=True,
                source_root=str(Path.cwd().resolve()),
            )

    manifest, provenance_root, gate0, spec, context, limits, fees = _setup(tmp_path)
    monkeypatch.setattr(runtime_provenance_module, "_PROVIDER", _WrongCommitProvider())
    with pytest.raises(CryptoGovernanceError, match="runtime code provenance rejected"):
        run_protected_crypto_evaluation(
            manifest=manifest,
            provenance_root=provenance_root,
            gate0_verdict=gate0,  # type: ignore[arg-type]
            spec=spec,
            holdout=context,
            cohort_members=["CMC:2"],
            run_id="wrong-runtime",
            execution_limits=limits,
            taker_fees=fees,
        )


@pytest.mark.parametrize(
    ("ledger", "expected_status"),
    [
        (
            MarketEventLedger.from_events(
                [
                    _market_event(
                        timestamp="2024-01-03T00:00:00Z",
                        event="DELISTING_ANNOUNCED",
                    )
                ]
            ),
            "FILLED",
        ),
        (
            MarketEventLedger.from_events(
                [
                    _market_event(
                        timestamp="2024-01-04T00:00:00Z",
                        event="DELISTING_CONFIRMED",
                    )
                ]
            ),
            "WRITTEN_DOWN",
        ),
    ],
)
def test_runner_delivers_sealed_announcement_and_terminal_events_to_evaluations(
    tmp_path: Path,
    ledger: MarketEventLedger,
    expected_status: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import quant_trade.research.crypto_runner as crypto_runner

    observed_ledgers: list[MarketEventLedger] = []
    original_evaluate = crypto_runner.evaluate

    def recording_evaluate(*args, **kwargs):
        observed_ledgers.append(kwargs["market_events"])
        return original_evaluate(*args, **kwargs)

    monkeypatch.setattr(crypto_runner, "evaluate", recording_evaluate)
    manifest, provenance_root, gate0, spec, context, limits, fees = _setup(
        tmp_path,
        holdout_market_events=ledger,
        delisting_recovery=1.0,
    )
    run = run_protected_crypto_evaluation(
        manifest=manifest,
        provenance_root=provenance_root,
        gate0_verdict=gate0,  # type: ignore[arg-type]
        spec=spec,
        holdout=context,
        cohort_members=["CMC:2"],
        run_id="event-run",
        execution_limits=limits,
        taker_fees=fees,
    )

    assert run.artifact["market_events"] == ledger.to_dict()
    assert run.artifact["market_events_component_digest"] == (
        canonical_market_event_ledger_digest(ledger)
    )
    assert observed_ledgers == [ledger, ledger, ledger, ledger, ledger]
    for result in (run.candidate_result, run.control_result):
        event_sells = [
            execution
            for execution in result.executions
            if execution.instrument_id == "CMC:2"
            and execution.side == "sell"
            and execution.order_intent == "FORCED_EXIT"
        ]
        assert event_sells
        assert event_sells[-1].status == expected_status


def test_runner_rejects_sensitive_panel_event_without_ledger_before_evaluate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import quant_trade.research.crypto_runner as crypto_runner

    manifest, provenance_root, gate0, spec, context, limits, fees = _setup(
        tmp_path,
        holdout_panel_market_event="RANK_EXIT|DELISTING_CONFIRMED",
    )
    evaluated = False

    def forbidden_evaluate(*args, **kwargs):
        nonlocal evaluated
        evaluated = True
        raise AssertionError("evaluate must not run for an unbacked sensitive event")

    monkeypatch.setattr(crypto_runner, "evaluate", forbidden_evaluate)
    with pytest.raises(CryptoGovernanceError, match="not exactly backed"):
        run_protected_crypto_evaluation(
            manifest=manifest,
            provenance_root=provenance_root,
            gate0_verdict=gate0,  # type: ignore[arg-type]
            spec=spec,
            holdout=context,
            cohort_members=["CMC:2"],
            run_id="unbacked-panel-event",
            execution_limits=limits,
            taker_fees=fees,
        )
    assert evaluated is False


def test_runner_accepts_exact_sensitive_panel_and_ledger_event(tmp_path: Path) -> None:
    ledger = MarketEventLedger.from_events(
        [
            _market_event(
                timestamp="2024-01-04T00:00:00Z",
                event="DELISTING_CONFIRMED",
                recovery=7.5,
            )
        ]
    )
    manifest, provenance_root, gate0, spec, context, limits, fees = _setup(
        tmp_path,
        holdout_market_events=ledger,
        holdout_panel_market_event="DELISTING_CONFIRMED",
        holdout_panel_recovery=7.5,
        delisting_recovery=1.0,
    )

    run = run_protected_crypto_evaluation(
        manifest=manifest,
        provenance_root=provenance_root,
        gate0_verdict=gate0,  # type: ignore[arg-type]
        spec=spec,
        holdout=context,
        cohort_members=["CMC:2"],
        run_id="exact-panel-event",
        execution_limits=limits,
        taker_fees=fees,
    )

    assert run.artifact["market_events"] == ledger.to_dict()


def test_runner_allows_derived_panel_events_without_ledger(tmp_path: Path) -> None:
    manifest, provenance_root, gate0, spec, context, limits, fees = _setup(
        tmp_path,
        holdout_panel_market_event="RANK_EXIT|GAP",
    )

    run = run_protected_crypto_evaluation(
        manifest=manifest,
        provenance_root=provenance_root,
        gate0_verdict=gate0,  # type: ignore[arg-type]
        spec=spec,
        holdout=context,
        cohort_members=["CMC:2"],
        run_id="derived-panel-event",
        execution_limits=limits,
        taker_fees=fees,
    )

    assert run.artifact["market_events"] == MarketEventLedger.from_events(()).to_dict()


@pytest.mark.parametrize(
    ("ledger_event", "panel_recovery", "error"),
    [
        ("DELISTING_ANNOUNCED", None, "not exactly backed"),
        ("DELISTING_CONFIRMED", 6.0, "recovery does not match"),
    ],
)
def test_runner_rejects_panel_and_ledger_event_mismatch(
    tmp_path: Path,
    ledger_event: str,
    panel_recovery: float | None,
    error: str,
) -> None:
    recovery = 7.5 if ledger_event == "DELISTING_CONFIRMED" else None
    ledger = MarketEventLedger.from_events(
        [
            _market_event(
                timestamp="2024-01-04T00:00:00Z",
                event=ledger_event,
                recovery=recovery,
            )
        ]
    )
    manifest, provenance_root, gate0, spec, context, limits, fees = _setup(
        tmp_path,
        holdout_market_events=ledger,
        holdout_panel_market_event="DELISTING_CONFIRMED",
        holdout_panel_recovery=panel_recovery,
        delisting_recovery=1.0,
    )

    with pytest.raises(CryptoGovernanceError, match=error):
        run_protected_crypto_evaluation(
            manifest=manifest,
            provenance_root=provenance_root,
            gate0_verdict=gate0,  # type: ignore[arg-type]
            spec=spec,
            holdout=context,
            cohort_members=["CMC:2"],
            run_id="mismatched-panel-event",
            execution_limits=limits,
            taker_fees=fees,
        )


def test_runner_rejects_untrusted_or_mismatched_manifest_and_gate0(tmp_path: Path) -> None:
    manifest, provenance_root, gate0, spec, context, limits, fees = _setup(tmp_path)
    with pytest.raises(CryptoGovernanceError, match="manifest identity/digest"):
        run_protected_crypto_evaluation(
            manifest=replace(manifest, notes=("changes digest",)),
            provenance_root=provenance_root,
            gate0_verdict=gate0,  # type: ignore[arg-type]
            spec=spec,
            holdout=context,
            cohort_members=["CMC:2"],
            run_id="candidate-run",
            execution_limits=limits,
            taker_fees=fees,
        )


def test_runner_rehashes_manifest_components_before_any_evaluation(tmp_path: Path) -> None:
    manifest, provenance_root, gate0, spec, context, limits, fees = _setup(tmp_path)
    (provenance_root / "holdout.panel.json").write_bytes(b"tampered after the manifest was sealed")
    with pytest.raises(CryptoManifestError, match="component byte hash mismatch"):
        run_protected_crypto_evaluation(
            manifest=manifest,
            provenance_root=provenance_root,
            gate0_verdict=gate0,  # type: ignore[arg-type]
            spec=spec,
            holdout=context,
            cohort_members=["CMC:2"],
            run_id="candidate-run",
            execution_limits=limits,
            taker_fees=fees,
        )


def test_runner_rejects_in_memory_panel_not_identical_to_manifest_component(
    tmp_path: Path,
) -> None:
    manifest, provenance_root, gate0, spec, context, limits, fees = _setup(tmp_path)
    fabricated = context.panel.copy()
    fabricated.loc[fabricated.index[-1], "close"] *= 10
    with pytest.raises(CryptoGovernanceError, match="canonical bytes hashed by the manifest"):
        run_protected_crypto_evaluation(
            manifest=manifest,
            provenance_root=provenance_root,
            gate0_verdict=gate0,  # type: ignore[arg-type]
            spec=spec,
            holdout=RevealedHoldoutContext(
                context.holdout_directory,
                fabricated,
                context.market_events,
            ),
            cohort_members=["CMC:2"],
            run_id="candidate-run",
            execution_limits=limits,
            taker_fees=fees,
        )


def test_runner_rejects_market_event_ledger_not_identical_to_manifest_component(
    tmp_path: Path,
) -> None:
    manifest, provenance_root, gate0, spec, context, limits, fees = _setup(tmp_path)
    fabricated_events = MarketEventLedger.from_events(
        [
            _market_event(
                timestamp="2024-01-02T00:00:00Z",
                event="DELISTING_ANNOUNCED",
            )
        ]
    )
    with pytest.raises(CryptoGovernanceError, match="canonical bytes hashed by the manifest"):
        run_protected_crypto_evaluation(
            manifest=manifest,
            provenance_root=provenance_root,
            gate0_verdict=gate0,  # type: ignore[arg-type]
            spec=spec,
            holdout=RevealedHoldoutContext(
                context.holdout_directory,
                context.panel,
                fabricated_events,
            ),
            cohort_members=["CMC:2"],
            run_id="candidate-run",
            execution_limits=limits,
            taker_fees=fees,
        )


def test_runner_rejects_a_fabricated_pass_verdict(tmp_path: Path) -> None:
    manifest, provenance_root, gate0, spec, context, limits, fees = _setup(tmp_path)
    fabricated = replace(gate0, evidence=Gate0Evidence())
    with pytest.raises(CryptoGateError, match="Gate 0"):
        run_protected_crypto_evaluation(
            manifest=manifest,
            provenance_root=provenance_root,
            gate0_verdict=fabricated,
            spec=spec,
            holdout=context,
            cohort_members=["CMC:2"],
            run_id="candidate-run",
            execution_limits=limits,
            taker_fees=fees,
        )
    blocked = evaluate_gate0(VenuePolicy(), None)
    with pytest.raises(CryptoGateError, match="Gate 0"):
        run_protected_crypto_evaluation(
            manifest=manifest,
            provenance_root=provenance_root,
            gate0_verdict=blocked,
            spec=spec,
            holdout=context,
            cohort_members=["CMC:2"],
            run_id="candidate-run",
            execution_limits=limits,
            taker_fees=fees,
        )


def test_runner_requires_one_explicit_reveal_and_exact_holdout_range(tmp_path: Path) -> None:
    manifest, provenance_root, gate0, spec, context, limits, fees = _setup(
        tmp_path / "unrevealed", revealed=False
    )
    with pytest.raises(CryptoGovernanceError, match="exactly one reveal"):
        run_protected_crypto_evaluation(
            manifest=manifest,
            provenance_root=provenance_root,
            gate0_verdict=gate0,  # type: ignore[arg-type]
            spec=spec,
            holdout=context,
            cohort_members=["CMC:2"],
            run_id="candidate-run",
            execution_limits=limits,
            taker_fees=fees,
        )
    manifest, provenance_root, gate0, spec, context, limits, fees = _setup(tmp_path / "revealed")
    short = RevealedHoldoutContext(
        context.holdout_directory,
        context.panel[context.panel["timestamp"] < pd.Timestamp("2024-01-04", tz="UTC")],
        context.market_events,
    )
    with pytest.raises(CryptoGovernanceError, match="exact sealed holdout range"):
        run_protected_crypto_evaluation(
            manifest=manifest,
            provenance_root=provenance_root,
            gate0_verdict=gate0,  # type: ignore[arg-type]
            spec=spec,
            holdout=short,
            cohort_members=["CMC:2"],
            run_id="candidate-run",
            execution_limits=limits,
            taker_fees=fees,
        )


def test_runner_rejects_unsealed_execution_inputs_and_supplemental_metrics(
    tmp_path: Path,
) -> None:
    manifest, provenance_root, gate0, spec, context, limits, fees = _setup(tmp_path)
    with pytest.raises(CryptoGovernanceError, match="cover every tradable symbol"):
        run_protected_crypto_evaluation(
            manifest=manifest,
            provenance_root=provenance_root,
            gate0_verdict=gate0,  # type: ignore[arg-type]
            spec=spec,
            holdout=context,
            cohort_members=["CMC:2"],
            run_id="candidate-run",
            execution_limits={"CMC:2": ExecutionLimits(min_notional_usd=5.0)},
            taker_fees=fees,
        )
    with pytest.raises(TypeError, match="supplemental_evidence"):
        run_protected_crypto_evaluation(
            manifest=manifest,
            provenance_root=provenance_root,
            gate0_verdict=gate0,  # type: ignore[arg-type]
            spec=spec,
            holdout=context,
            cohort_members=["CMC:2"],
            run_id="candidate-run",
            execution_limits=limits,
            taker_fees=fees,
            supplemental_evidence={"dataset_digest": "x"},
        )


def test_selection_runner_never_reads_holdout_and_is_not_promotable(tmp_path: Path) -> None:
    manifest, provenance_root, gate0, spec, context, limits, fees = _setup(tmp_path, revealed=False)
    selection_panel = _panel("2023-01-01")
    selection = SelectionContext(
        context.holdout_directory,
        selection_panel,
        MarketEventLedger.from_events(()),
    )
    run = run_protected_crypto_selection(
        manifest=manifest,
        provenance_root=provenance_root,
        gate0_verdict=gate0,  # type: ignore[arg-type]
        spec=spec,
        selection=selection,
        cohort_members=["CMC:2"],
        run_id="selection-run",
        execution_limits=limits,
        taker_fees=fees,
    )
    assert run.promotable is False
    assert run.artifact["phase"] == "SELECTION"
    assert run.artifact["promotable"] is False
    assert run.artifact["holdout_reveal_count"] == 0
    assert "holdout" not in run.artifact


def test_selection_runner_does_not_read_reserved_holdout_component(tmp_path: Path) -> None:
    manifest, provenance_root, gate0, spec, context, limits, fees = _setup(tmp_path, revealed=False)
    (provenance_root / "holdout.panel.json").unlink()
    (provenance_root / "holdout.market-events.json").unlink()
    run = run_protected_crypto_selection(
        manifest=manifest,
        provenance_root=provenance_root,
        gate0_verdict=gate0,  # type: ignore[arg-type]
        spec=spec,
        selection=SelectionContext(
            context.holdout_directory,
            _panel("2023-01-01"),
            MarketEventLedger.from_events(()),
        ),
        cohort_members=["CMC:2"],
        run_id="selection-run",
        execution_limits=limits,
        taker_fees=fees,
    )
    assert run.artifact["phase"] == "SELECTION"


def test_selection_runner_rejects_tampered_market_event_component(tmp_path: Path) -> None:
    manifest, provenance_root, gate0, spec, context, limits, fees = _setup(tmp_path, revealed=False)
    (provenance_root / "selection.market-events.json").write_bytes(b"tampered")
    with pytest.raises(CryptoGovernanceError, match="selection component byte hash mismatch"):
        run_protected_crypto_selection(
            manifest=manifest,
            provenance_root=provenance_root,
            gate0_verdict=gate0,  # type: ignore[arg-type]
            spec=spec,
            selection=SelectionContext(
                context.holdout_directory,
                _panel("2023-01-01"),
                MarketEventLedger.from_events(()),
            ),
            cohort_members=["CMC:2"],
            run_id="selection-run",
            execution_limits=limits,
            taker_fees=fees,
        )


def test_selection_runner_rehashes_active_fee_source_bytes_before_evaluate(
    tmp_path: Path,
) -> None:
    manifest, provenance_root, gate0, spec, context, limits, fees = _setup(
        tmp_path,
        revealed=False,
    )
    fee_component = provenance_root / manifest.component_provenance["fee_source_cmc_1"]
    fee_component.write_bytes(b"tampered account fee response")

    with pytest.raises(CryptoGovernanceError, match="source byte hash mismatch"):
        run_protected_crypto_selection(
            manifest=manifest,
            provenance_root=provenance_root,
            gate0_verdict=gate0,  # type: ignore[arg-type]
            spec=spec,
            selection=SelectionContext(
                context.holdout_directory,
                _panel("2023-01-01"),
                MarketEventLedger.from_events(()),
            ),
            cohort_members=["CMC:2"],
            run_id="selection-run",
            execution_limits=limits,
            taker_fees=fees,
        )


def test_selection_runner_rejects_default_profiles_without_original_bytes(
    tmp_path: Path,
) -> None:
    manifest, provenance_root, gate0, spec, context, limits, fees = _setup(
        tmp_path,
        revealed=False,
    )
    default_spec = replace(
        spec,
        cost_policy={
            **dict(spec.cost_policy),
            "cost_profiles_digest": cost_profiles_digest(DEFAULT_TIER_PROFILES),
        },
    )

    with pytest.raises(CryptoGovernanceError, match="source bytes are not a distinct"):
        _run_protected_crypto_selection(
            manifest=manifest,
            provenance_root=provenance_root,
            gate0_verdict=gate0,  # type: ignore[arg-type]
            spec=default_spec,
            selection=SelectionContext(
                context.holdout_directory,
                _panel("2023-01-01"),
                MarketEventLedger.from_events(()),
            ),
            cohort_members=["CMC:2"],
            run_id="selection-run",
            execution_limits=limits,
            taker_fees=fees,
        )


def test_runner_rejects_fee_metadata_for_another_symbol(tmp_path: Path) -> None:
    manifest, provenance_root, gate0, spec, context, limits, fees = _setup(
        tmp_path,
        revealed=False,
    )
    wrong_fees = dict(fees)
    wrong_fees["CMC:2"] = replace(wrong_fees["CMC:2"], venue_symbol="CMC:999")
    wrong_spec = replace(
        spec,
        cost_policy={
            **dict(spec.cost_policy),
            "taker_fees_digest": taker_fees_digest(wrong_fees),
        },
    )

    with pytest.raises(CryptoGovernanceError, match="venue/symbol metadata"):
        run_protected_crypto_selection(
            manifest=manifest,
            provenance_root=provenance_root,
            gate0_verdict=gate0,  # type: ignore[arg-type]
            spec=wrong_spec,
            selection=SelectionContext(
                context.holdout_directory,
                _panel("2023-01-01"),
                MarketEventLedger.from_events(()),
            ),
            cohort_members=["CMC:2"],
            run_id="selection-run",
            execution_limits=limits,
            taker_fees=wrong_fees,
        )


def test_runner_rejects_control_that_changes_more_than_declared_variable(tmp_path: Path) -> None:
    manifest, provenance_root, gate0, spec, context, limits, fees = _setup(tmp_path, revealed=False)
    invalid_spec = replace(
        spec,
        control={
            "comparison_variable": "liquid_band",
            "liquid_band": True,
            "top_n": 2,
        },
    )
    with pytest.raises(CryptoGovernanceError, match="exactly control.comparison_variable"):
        run_protected_crypto_selection(
            manifest=manifest,
            provenance_root=provenance_root,
            gate0_verdict=gate0,  # type: ignore[arg-type]
            spec=invalid_spec,
            selection=SelectionContext(
                context.holdout_directory,
                _panel("2023-01-01"),
                MarketEventLedger.from_events(()),
            ),
            cohort_members=["CMC:2"],
            run_id="selection-run",
            execution_limits=limits,
            taker_fees=fees,
        )


def test_selection_runner_rejects_any_reveal_or_future_row(tmp_path: Path) -> None:
    manifest, provenance_root, gate0, spec, context, limits, fees = _setup(tmp_path)
    with pytest.raises(CryptoGovernanceError, match="zero reveals"):
        run_protected_crypto_selection(
            manifest=manifest,
            provenance_root=provenance_root,
            gate0_verdict=gate0,  # type: ignore[arg-type]
            spec=spec,
            selection=SelectionContext(
                context.holdout_directory,
                _panel("2023-01-01"),
                MarketEventLedger.from_events(()),
            ),
            cohort_members=["CMC:2"],
            run_id="selection-run",
            execution_limits=limits,
            taker_fees=fees,
        )
    manifest, provenance_root, gate0, spec, context, limits, fees = _setup(
        tmp_path / "unrevealed", revealed=False
    )
    future = pd.concat([_panel("2023-01-01"), _panel("2024-01-01")], ignore_index=True)
    with pytest.raises(CryptoGovernanceError, match="outside the sealed selection"):
        run_protected_crypto_selection(
            manifest=manifest,
            provenance_root=provenance_root,
            gate0_verdict=gate0,  # type: ignore[arg-type]
            spec=spec,
            selection=SelectionContext(
                context.holdout_directory,
                future,
                MarketEventLedger.from_events(()),
            ),
            cohort_members=["CMC:2"],
            run_id="selection-run",
            execution_limits=limits,
            taker_fees=fees,
        )
