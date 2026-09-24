"""The engine composes trusted estimators; these tests check the composition.

The load-bearing case is the best-of-100 unskilled walks: PSR alone calls it
significant, the deflated Sharpe at 100 trials must not.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest
from audit_fixtures import (
    benchmark_lower_drift,
    best_of_n_walks,
    csv_bytes,
    positive_drift,
    trades_following,
    trades_frame,
    variants_bytes,
)

from quant_trade.audit.engine import run_audit, sharpe_sampling_variance
from quant_trade.audit.schema import DeclaredMetadata, build_inputs
from quant_trade.evidence.canonical_json import canonical_dumps

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _run(inputs, **kw):
    return run_audit(inputs, now=NOW, audit_id="fixed", bootstrap_samples=300, **kw)


def _status(result, name: str) -> str:
    return {d.name: d.status for d in result.verdict.dimensions}[name]


def test_best_of_100_walks_is_caught_by_the_deflated_sharpe() -> None:
    winner, matrix = best_of_n_walks(trials=100, n=512)
    inputs = build_inputs(csv_bytes(winner), DeclaredMetadata(trials=100, cost_bps_per_side=5))
    result = _run(inputs)
    payload = result.model_dump(mode="json")
    psr = payload["significance"]["psr"]["value"]
    dsr_100 = payload["multiplicity"]["dsr_at_declared"]["value"]
    assert psr > 0.9
    assert dsr_100 < 0.7
    assert psr - dsr_100 > 0.3
    assert _status(result, "multiplicity") in {"WEAK", "FAIL"}
    assert result.verdict.overall in {"C", "D"}
    # the variance policy: no variants uploaded, so the floor is what is used
    assert payload["multiplicity"]["sharpe_variance_used"]["value"] == pytest.approx(
        payload["multiplicity"]["floor"]["value"]
    )
    assert payload["multiplicity"]["observed_across_variants"]["evidence"] == "NOT_MEASURED"


def test_variants_upload_enables_cscv_and_the_observed_variance() -> None:
    winner, matrix = best_of_n_walks(trials=40, n=512)
    inputs = build_inputs(
        csv_bytes(winner),
        DeclaredMetadata(trials=40, cost_bps_per_side=5),
        variants_bytes=variants_bytes(matrix),
    )
    result = _run(inputs)
    payload = result.model_dump(mode="json")
    assert payload["cscv"]["status"] == "MEASURED"
    assert payload["cscv"]["parameter_variants"] == 40
    assert 0.0 <= payload["cscv"]["pbo"]["value"] <= 1.0
    observed = payload["multiplicity"]["observed_across_variants"]["value"]
    floor = payload["multiplicity"]["floor"]["value"]
    assert payload["multiplicity"]["sharpe_variance_used"]["value"] == pytest.approx(
        max(observed, floor)
    )


def test_honest_curve_with_everything_declared_reaches_class_a() -> None:
    n = 1500
    inputs = build_inputs(
        csv_bytes(positive_drift(n)),
        DeclaredMetadata(trials=3, cost_bps_per_side=5, oos_start="2023-01-01"),
        trades_bytes=csv_bytes(trades_following(positive_drift(n))),
        benchmark_bytes=csv_bytes(benchmark_lower_drift(n)),
    )
    result = _run(inputs)
    statuses = {d.name: d.status for d in result.verdict.dimensions}
    assert statuses["statistical_significance"] == "PASS"
    assert statuses["multiplicity"] == "PASS"
    assert statuses["costs"] == "PASS"
    assert statuses["out_of_sample"] == "PASS"
    assert statuses["data_quality"] == "PASS"
    assert statuses["benchmark"] in {"PASS", "WEAK"}
    assert result.verdict.overall in {"A", "B"}
    payload = result.model_dump(mode="json")
    assert payload["seal"]["status"] == "DECLARED"
    assert payload["seal"]["holdout_seal"]["holdout_start"].startswith("2023-01-01")
    assert payload["holdout"]["in_sample"]["observations"]["value"] > 30
    assert payload["holdout"]["out_of_sample"]["observations"]["value"] > 30


def test_without_trades_or_holdout_the_class_is_capped_at_b() -> None:
    inputs = build_inputs(csv_bytes(positive_drift(1500)), DeclaredMetadata(trials=1))
    result = _run(inputs)
    assert _status(result, "costs") == "NOT_MEASURED"
    assert _status(result, "out_of_sample") == "NOT_MEASURED"
    assert _status(result, "benchmark") == "NOT_MEASURED"
    assert result.verdict.overall in {"B", "C", "D"}
    if _status(result, "statistical_significance") == "PASS":
        assert result.verdict.overall == "B"
    payload = result.model_dump(mode="json")
    assert payload["performance"]["win_rate"]["evidence"] == "NOT_MEASURED"
    assert payload["seal"]["holdout_seal"] is None


def test_holdout_outside_the_series_is_not_measured() -> None:
    inputs = build_inputs(csv_bytes(positive_drift(400)), DeclaredMetadata(oos_start="2030-01-01"))
    result = _run(inputs)
    payload = result.model_dump(mode="json")
    assert payload["holdout"]["status"] == "NOT_MEASURED"
    assert "outside" in payload["holdout"]["reason"]
    assert payload["seal"]["status"] == "NOT_MEASURED"


def test_holdout_gap_sign_and_short_side() -> None:
    frame = positive_drift(400)
    inputs = build_inputs(
        csv_bytes(frame), DeclaredMetadata(oos_start=str(frame["timestamp"].iloc[380].date()))
    )
    payload = _run(inputs).model_dump(mode="json")
    assert payload["holdout"]["status"] == "NOT_MEASURED"
    assert "fewer than" in payload["holdout"]["reason"]
    inputs = build_inputs(
        csv_bytes(frame), DeclaredMetadata(oos_start=str(frame["timestamp"].iloc[200].date()))
    )
    payload = _run(inputs).model_dump(mode="json")
    hold = payload["holdout"]
    assert hold["status"] == "MEASURED"
    assert hold["gap"]["value"] == pytest.approx(
        hold["in_sample"]["sharpe_annualised"]["value"]
        - hold["out_of_sample"]["sharpe_annualised"]["value"]
    )


def test_benchmark_overlap_below_ninety_percent_is_not_measured() -> None:
    frame = positive_drift(600)
    bench = benchmark_lower_drift(600).iloc[:300]
    inputs = build_inputs(csv_bytes(frame), DeclaredMetadata(), benchmark_bytes=csv_bytes(bench))
    payload = _run(inputs).model_dump(mode="json")
    assert payload["benchmark"]["status"] == "NOT_MEASURED"
    assert payload["benchmark"]["overlap_share"]["value"] == pytest.approx(0.5)


def test_benchmark_declared_not_applicable() -> None:
    inputs = build_inputs(
        csv_bytes(positive_drift(400)), DeclaredMetadata(benchmark_applicable=False)
    )
    assert _status(_run(inputs), "benchmark") == "NOT_APPLICABLE"


def test_too_short_series_is_class_d_with_nothing_measured() -> None:
    inputs = build_inputs(csv_bytes(positive_drift(12)), DeclaredMetadata())
    result = _run(inputs)
    assert result.verdict.overall == "D"
    assert _status(result, "data_quality") == "FAIL"
    payload = result.model_dump(mode="json")
    assert payload["bootstrap"]["status"] == "MEASURED"  # ten returns are enough for a band
    assert {f["code"] for f in payload["red_flags"]} >= {"TOO_FEW_OBSERVATIONS"}


def test_same_seed_same_bytes_and_no_nan() -> None:
    inputs = build_inputs(
        csv_bytes(positive_drift(500)),
        DeclaredMetadata(trials=7, description="probamos 7 variantes"),
        trades_bytes=csv_bytes(trades_frame(20)),
    )
    first = canonical_dumps(_run(inputs).model_dump(mode="json"))
    second = canonical_dumps(_run(inputs).model_dump(mode="json"))
    assert first == second
    assert "NaN" not in first and "Infinity" not in first
    other = canonical_dumps(_run(inputs, seed=99).model_dump(mode="json"))
    assert other != first


def test_client_description_claims_are_reported_not_blocking() -> None:
    inputs = build_inputs(
        csv_bytes(positive_drift(400)),
        DeclaredMetadata(description="estrategia rentable, makes money every month"),
    )
    result = _run(inputs)
    patterns = {finding["pattern"] for finding in result.client_text_findings}
    assert r"\brentable\b" in patterns
    assert r"\bmakes? money\b" in patterns


def test_sharpe_sampling_variance_formula() -> None:
    assert sharpe_sampling_variance(0.0, 0.0, 3.0, 101) == pytest.approx(1.0 / 100)
    assert sharpe_sampling_variance(0.1, 0.0, 3.0, 2) == pytest.approx(1.0 + 0.5 * 0.01)
    assert sharpe_sampling_variance(0.1, 0.0, 3.0, 1) == 0.0


def test_variants_matrix_is_trimmed_to_a_multiple_of_the_partitions() -> None:
    winner, matrix = best_of_n_walks(trials=5, n=100)
    inputs = build_inputs(
        csv_bytes(winner), DeclaredMetadata(trials=5), variants_bytes=variants_bytes(matrix)
    )
    payload = _run(inputs).model_dump(mode="json")
    assert payload["cscv"]["observations_used"] == 96
    assert payload["cscv"]["observations_dropped"] == 4
    assert isinstance(matrix, np.ndarray)
