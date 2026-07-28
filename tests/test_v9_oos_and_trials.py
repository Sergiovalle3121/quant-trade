"""Out-of-sample discipline and trial multiplicity.

The two ways a backtest lies to itself: it lets the selector see the answer,
and it forgets how many answers it tried. These tests pin both.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from quant_trade.v9.oos import (
    HOLDOUT_FRACTION,
    TRAIN_FRACTION,
    WALK_FORWARD_FRACTION,
    HoldoutSeal,
    HoldoutVerdict,
    HoldoutViolation,
    InsufficientData,
    evaluate_holdout,
    plan_splits,
    run_walk_forward,
)
from quant_trade.v9.trial_ledger import (
    TRIAL_STATUS_FAILED,
    GlobalTrialLedger,
    TrialLedgerError,
    TrialRecord,
    deflated_sharpe,
    require_promotable_ledger,
)

# --- splits -----------------------------------------------------------------------


def test_the_split_is_the_preregistered_fifty_thirty_twenty() -> None:
    plan = plan_splits(1_000)
    assert plan.train_rows == 500
    assert plan.walk_forward_rows == 300
    assert plan.holdout_rows == 200
    assert (TRAIN_FRACTION, WALK_FORWARD_FRACTION, HOLDOUT_FRACTION) == (0.5, 0.3, 0.2)


def test_the_holdout_is_the_most_recent_slice() -> None:
    plan = plan_splits(1_000)
    assert plan.holdout_start == 800
    assert plan.to_dict()["holdout_start_index"] == 800


def test_too_little_data_is_refused() -> None:
    with pytest.raises(InsufficientData):
        plan_splits(4)


# --- walk-forward -------------------------------------------------------------------


def test_selection_only_ever_sees_the_past() -> None:
    """The whole claim of walk-forward, asserted directly."""
    plan = plan_splits(1_000)
    seen: list[tuple[int, int]] = []

    def evaluate(variant: str, start: int, end: int) -> list[float]:
        seen.append((start, end))
        return [0.001] * max(0, end - start)

    result = run_walk_forward(
        1_000, ["a", "b"], evaluate, plan=plan, test_size=100, purge_bars=5, embargo_bars=1
    )
    assert result.window_count > 0
    for window in result.windows:
        # Every selection call for this window ended before its test block.
        assert window.selection_end_index <= window.test_start_index - 6
        assert window.test_end_index <= plan.walk_forward_end
    # Nothing was ever read past the walk-forward boundary.
    assert max(end for _start, end in seen) <= plan.walk_forward_end


def test_walk_forward_never_touches_the_holdout() -> None:
    plan = plan_splits(1_000)
    touched: list[int] = []

    def evaluate(variant: str, start: int, end: int) -> list[float]:
        touched.append(end)
        return [0.0] * max(0, end - start)

    run_walk_forward(1_000, ["a"], evaluate, plan=plan, test_size=100)
    assert max(touched) < plan.holdout_start + 1
    assert all(end <= plan.walk_forward_end for end in touched)


def test_each_window_may_select_a_different_variant() -> None:
    """A per-window choice is the difference from a full-sample fit."""
    plan = plan_splits(1_000)

    def evaluate(variant: str, start: int, end: int) -> list[float]:
        length = max(0, end - start)
        # "a" wins early, "b" wins late.
        # "a" is the better choice early, "b" late; keyed on the window's
        # right edge because selection always anchors at index 0.
        early = end < 620
        rate = (0.002 if early else -0.001) if variant == "a" else (-0.001 if early else 0.002)
        return [rate] * length

    result = run_walk_forward(1_000, ["a", "b"], evaluate, plan=plan, test_size=50)
    assert result.distinct_variants >= 2


def test_only_test_block_returns_enter_the_oos_series() -> None:
    plan = plan_splits(1_000)

    def evaluate(variant: str, start: int, end: int) -> list[float]:
        return [0.001] * max(0, end - start)

    result = run_walk_forward(1_000, ["a"], evaluate, plan=plan, test_size=100)
    assert len(result.oos_returns) == result.window_count * 100
    assert len(result.oos_returns) < plan.total_rows


def test_a_purge_that_swallows_the_selection_window_is_reported() -> None:
    plan = plan_splits(100)

    def evaluate(variant: str, start: int, end: int) -> list[float]:
        return [0.0] * max(0, end - start)

    result = run_walk_forward(
        100,
        ["a"],
        evaluate,
        plan=plan,
        test_size=10,
        purge_bars=1_000,
        min_selection_rows=10,
    )
    assert result.problems
    assert result.window_count == 0


def test_walk_forward_needs_at_least_one_variant() -> None:
    with pytest.raises(InsufficientData):
        run_walk_forward(1_000, [], lambda v, s, e: [], plan=plan_splits(1_000), test_size=10)


# --- holdout seal ----------------------------------------------------------------------


def test_the_holdout_cannot_open_before_the_config_freezes() -> None:
    seal = HoldoutSeal(plan_splits(1_000))
    with pytest.raises(HoldoutViolation, match="before the configuration is frozen"):
        seal.reveal(reason="peeking")


def test_the_holdout_opens_exactly_once() -> None:
    seal = HoldoutSeal(plan_splits(1_000))
    seal.freeze(variant="a", config={"threshold": 1})
    assert seal.reveal(reason="final scoring") == (800, 1_000)
    with pytest.raises(HoldoutViolation, match="already been revealed"):
        seal.reveal(reason="one more look")


def test_freezing_after_revealing_is_a_violation() -> None:
    seal = HoldoutSeal(plan_splits(1_000))
    seal.freeze(variant="a", config={})
    seal.reveal(reason="scoring")
    with pytest.raises(HoldoutViolation, match="would make the choice in-sample"):
        seal.freeze(variant="b", config={})


def test_the_frozen_hash_changes_with_the_configuration() -> None:
    first = HoldoutSeal(plan_splits(1_000))
    first.freeze(variant="a", config={"threshold": 1})
    second = HoldoutSeal(plan_splits(1_000))
    second.freeze(variant="a", config={"threshold": 2})
    assert first.frozen_hash != second.frozen_hash


# --- holdout verdict --------------------------------------------------------------------


def _verdict(**overrides) -> HoldoutVerdict:
    payload = {
        "frozen_variant": "a",
        "frozen_hash": "h" * 64,
        "holdout_observations": 200,
        "holdout_net_return": 0.05,
        "holdout_net_return_2x_costs": 0.02,
        "holdout_net_return_3x_costs": 0.01,
        "full_sample_net_return": 0.30,
        "oos_net_return": 0.08,
        "bootstrap_p05": 0.01,
        "probabilistic_sharpe": 0.99,
        "deflated_sharpe": 0.97,
        "liquidations": 0,
        "failed_reconciliations": 0,
        "unverified_inputs": [],
        "benchmark_returns": {"cash": 0.01, "buy_and_hold": 0.02},
    }
    payload.update(overrides)
    return HoldoutVerdict(**payload)


def test_a_clean_holdout_promotes() -> None:
    """Otherwise the gate would be an unconditional no."""
    verdict = evaluate_holdout(_verdict())
    assert verdict.promoted
    assert verdict.to_dict()["decision"] == "BACKTEST_CANDIDATE"


def test_a_glowing_full_sample_never_rescues_a_negative_holdout() -> None:
    verdict = evaluate_holdout(_verdict(holdout_net_return=-0.02, full_sample_net_return=2.50))
    assert not verdict.promoted
    assert any("holdout_net_positive" in r for r in verdict.rejection_reasons)
    assert verdict.to_dict()["decision"] == "MEASURED_REJECTED"


def test_a_holdout_that_dies_at_2x_costs_is_rejected() -> None:
    verdict = evaluate_holdout(_verdict(holdout_net_return_2x_costs=-0.001))
    assert not verdict.promoted
    assert any("2x_costs" in r for r in verdict.rejection_reasons)


@pytest.mark.parametrize(
    ("field", "value", "gate"),
    [
        ("bootstrap_p05", -0.01, "bootstrap_p05_positive"),
        ("bootstrap_p05", None, "bootstrap_p05_positive"),
        ("probabilistic_sharpe", 0.5, "probabilistic_sharpe"),
        ("deflated_sharpe", 0.5, "deflated_sharpe"),
        ("deflated_sharpe", None, "deflated_sharpe"),
        ("liquidations", 1, "zero_liquidations"),
        ("failed_reconciliations", 1, "zero_failed_reconciliations"),
        ("unverified_inputs", ["assumed fee"], "no_unverified_inputs"),
    ],
)
def test_each_gate_rejects_on_its_own_condition(field: str, value: object, gate: str) -> None:
    verdict = evaluate_holdout(_verdict(**{field: value}))
    assert not verdict.promoted
    assert any(gate in r for r in verdict.rejection_reasons)


def test_losing_to_a_benchmark_is_rejected() -> None:
    verdict = evaluate_holdout(_verdict(benchmark_returns={"buy_and_hold": 0.90}))
    assert not verdict.promoted
    assert any("beats_buy_and_hold" in r for r in verdict.rejection_reasons)


def test_an_undefined_deflated_sharpe_is_never_treated_as_passing() -> None:
    verdict = evaluate_holdout(_verdict(deflated_sharpe=None))
    assert not verdict.promoted


# --- trial ledger -------------------------------------------------------------------------


def _trial(path: Path, **overrides) -> TrialRecord:
    payload = {
        "trial_id": "t1",
        "hypothesis_id": "H1",
        "variant_id": "v1",
        "code_sha": "c" * 40,
        "config_sha": "f" * 64,
        "dataset_sha": "d" * 64,
        "seed": 1,
    }
    payload.update(overrides)
    return TrialRecord(**payload)


def test_a_byte_identical_reproduction_is_the_same_trial(tmp_path: Path) -> None:
    ledger = GlobalTrialLedger(tmp_path / "trials.jsonl")
    first = ledger.register(_trial(tmp_path))
    second = ledger.register(_trial(tmp_path))
    assert first["kind"] == "trial"
    assert second["kind"] == "reproduction"
    stats = ledger.stats()
    assert stats.distinct_trials == 1
    # The rerun is still written down: "we ran it again" is evidence.
    assert stats.duplicate_reproductions == 1
    assert stats.total_records == 2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("variant_id", "v2"),
        ("config_sha", "0" * 64),
        ("dataset_sha", "1" * 64),
        ("seed", 99),
        ("code_sha", "e" * 40),
    ],
)
def test_any_other_change_is_a_new_trial(tmp_path: Path, field: str, value: object) -> None:
    ledger = GlobalTrialLedger(tmp_path / "trials.jsonl")
    ledger.register(_trial(tmp_path))
    ledger.register(_trial(tmp_path, **{field: value}))
    assert ledger.stats().distinct_trials == 2


def test_failed_trials_still_count_towards_multiplicity(tmp_path: Path) -> None:
    """Counting only what survived is how a search of fifty becomes 'one trial'."""
    ledger = GlobalTrialLedger(tmp_path / "trials.jsonl")
    for index in range(5):
        record = _trial(tmp_path, trial_id=f"t{index}", variant_id=f"v{index}")
        ledger.register(record)
        ledger.complete(
            record,
            oos_sharpe=None,
            oos_total_return=None,
            status=TRIAL_STATUS_FAILED,
        )
    stats = ledger.stats()
    assert stats.distinct_trials == 5
    assert stats.failed_trials == 5


def test_the_ledger_is_hash_chained_and_tamper_evident(tmp_path: Path) -> None:
    path = tmp_path / "trials.jsonl"
    ledger = GlobalTrialLedger(path)
    for index in range(3):
        ledger.register(_trial(tmp_path, trial_id=f"t{index}", variant_id=f"v{index}"))
    assert ledger.verify_chain() == []
    lines = path.read_text().splitlines()
    path.write_text("\n".join([lines[0], lines[2]]) + "\n")  # drop the middle
    assert ledger.verify_chain() != []


def test_cross_trial_variance_is_computed_from_observed_sharpes(tmp_path: Path) -> None:
    ledger = GlobalTrialLedger(tmp_path / "trials.jsonl")
    for index, sharpe in enumerate([0.1, 0.4, -0.2, 0.7]):
        record = _trial(tmp_path, trial_id=f"t{index}", variant_id=f"v{index}")
        ledger.register(record)
        ledger.complete(record, oos_sharpe=sharpe, oos_total_return=sharpe / 10)
    stats = ledger.stats()
    assert stats.distinct_trials == 4
    assert stats.sharpe_variance > 0
    assert stats.sharpes == sorted([0.1, 0.4, -0.2, 0.7])


def test_a_missing_ledger_blocks_promotion() -> None:
    with pytest.raises(TrialLedgerError, match="requires a persistent trial ledger"):
        require_promotable_ledger(None)


def test_an_empty_ledger_blocks_promotion(tmp_path: Path) -> None:
    with pytest.raises(TrialLedgerError, match="is empty"):
        require_promotable_ledger(GlobalTrialLedger(tmp_path / "trials.jsonl"))


def test_a_broken_chain_blocks_promotion(tmp_path: Path) -> None:
    path = tmp_path / "trials.jsonl"
    ledger = GlobalTrialLedger(path)
    for index in range(3):
        ledger.register(_trial(tmp_path, trial_id=f"t{index}", variant_id=f"v{index}"))
    lines = path.read_text().splitlines()
    path.write_text("\n".join([lines[0], lines[2]]) + "\n")
    with pytest.raises(TrialLedgerError, match="hash chain is broken"):
        require_promotable_ledger(ledger)


def test_zero_variance_across_heterogeneous_trials_blocks(tmp_path: Path) -> None:
    """Identical outcomes from different experiments means the numbers are fake."""
    ledger = GlobalTrialLedger(tmp_path / "trials.jsonl")
    for index in range(4):
        record = _trial(tmp_path, trial_id=f"t{index}", variant_id=f"v{index}")
        ledger.register(record)
        ledger.complete(record, oos_sharpe=0.25, oos_total_return=0.1)
    with pytest.raises(TrialLedgerError, match="cross-trial Sharpe variance is zero"):
        require_promotable_ledger(ledger)


def test_a_healthy_ledger_is_accepted(tmp_path: Path) -> None:
    ledger = GlobalTrialLedger(tmp_path / "trials.jsonl")
    for index, sharpe in enumerate([0.1, 0.4, -0.2]):
        record = _trial(tmp_path, trial_id=f"t{index}", variant_id=f"v{index}")
        ledger.register(record)
        ledger.complete(record, oos_sharpe=sharpe, oos_total_return=sharpe / 10)
    stats = require_promotable_ledger(ledger)
    assert stats.distinct_trials == 3
    assert stats.sharpe_variance > 0


# --- deflated Sharpe --------------------------------------------------------------------------


def test_the_deflated_sharpe_falls_as_the_search_widens() -> None:
    one = deflated_sharpe(0.15, observations=500, trials=1, sharpe_variance=0.01)
    five = deflated_sharpe(0.15, observations=500, trials=5, sharpe_variance=0.01)
    fifty = deflated_sharpe(0.15, observations=500, trials=50, sharpe_variance=0.01)
    assert one > five > fifty


def test_dsr_is_strictly_below_psr_for_a_heterogeneous_search() -> None:
    import numpy as np
    import pandas as pd

    from quant_trade.metrics.statistics import probabilistic_sharpe_ratio

    rng = np.random.default_rng(7)
    returns = pd.Series(rng.normal(0.0015, 0.01, 500))
    psr = probabilistic_sharpe_ratio(returns)
    sharpe = float(returns.mean() / returns.std(ddof=1))
    dsr = deflated_sharpe(sharpe, observations=500, trials=40, sharpe_variance=0.02)
    assert dsr < psr


def test_a_single_trial_does_not_deflate() -> None:
    assert deflated_sharpe(0.15, observations=500, trials=1, sharpe_variance=0.0) == pytest.approx(
        deflated_sharpe(0.15, observations=500, trials=1, sharpe_variance=0.5)
    )


def test_too_few_observations_yield_no_confidence() -> None:
    assert deflated_sharpe(1.0, observations=1, trials=1, sharpe_variance=0.0) == 0.0


def test_the_summary_records_the_multiplicity_rule(tmp_path: Path) -> None:
    ledger = GlobalTrialLedger(tmp_path / "trials.jsonl")
    ledger.register(_trial(tmp_path))
    summary = ledger.summary()
    assert summary["artifact"] == "GLOBAL_TRIAL_LEDGER_SUMMARY"
    assert "byte-identical reproduction" in summary["multiplicity_rule"]
    assert summary["chain_intact"] is True
