"""Threshold boundaries and the class table, one case at a time."""

from __future__ import annotations

import pytest

from quant_trade.audit.costs import RecostRow
from quant_trade.audit.guard import find_claims
from quant_trade.audit.redflags import RedFlag
from quant_trade.audit.schema import Dimension
from quant_trade.audit.verdict import (
    BENCHMARK,
    COSTS,
    DATA_QUALITY,
    DIMENSION_ORDER,
    MULTIPLICITY,
    OUT_OF_SAMPLE,
    STATISTICAL,
    assess_benchmark,
    assess_costs,
    assess_data_quality,
    assess_multiplicity,
    assess_out_of_sample,
    assess_statistical,
    overall_class,
    summary,
)


def _dims(**statuses: str) -> list[Dimension]:
    base = {name: "PASS" for name in DIMENSION_ORDER}
    base.update(statuses)
    return [Dimension(name=name, status=status) for name, status in base.items()]  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("psr", "p5", "expected"),
    [
        (0.99, 0.01, "PASS"),
        (0.95, 0.0001, "PASS"),
        (0.949, 0.01, "WEAK"),
        (0.99, -0.01, "WEAK"),
        (0.80, -0.01, "WEAK"),
        (0.79, -0.01, "FAIL"),
        (0.10, 0.0, "FAIL"),
    ],
)
def test_statistical_boundaries(psr: float, p5: float, expected: str) -> None:
    assert assess_statistical(psr=psr, bootstrap_p5_sharpe=p5, observations=500).status == expected


def test_statistical_not_measured() -> None:
    dim = assess_statistical(psr=None, bootstrap_p5_sharpe=None, observations=2)
    assert dim.status == "NOT_MEASURED"


@pytest.mark.parametrize(
    ("dsr", "pbo", "expected"),
    [
        (0.99, None, "PASS"),
        (0.95, 0.2, "PASS"),
        (0.949, None, "WEAK"),
        (0.50, None, "WEAK"),
        (0.499, None, "FAIL"),
        (0.99, 0.5, "FAIL"),
    ],
)
def test_multiplicity_boundaries(dsr: float, pbo: float | None, expected: str) -> None:
    dim = assess_multiplicity(dsr=dsr, trials=10, pbo=pbo, statistical_status="PASS")
    assert dim.status == expected


def test_multiplicity_follows_unmeasured_statistics() -> None:
    dim = assess_multiplicity(dsr=None, trials=1, pbo=None, statistical_status="NOT_MEASURED")
    assert dim.status == "NOT_MEASURED"


def _rows(net_1x: float, net_3x: float) -> list[RecostRow]:
    return [
        RecostRow(m, 5.0 * m, 100.0, 0.0, net, 0.5, net / 10, 10)
        for m, net in ((0.0, 100.0), (1.0, net_1x), (2.0, (net_1x + net_3x) / 2), (3.0, net_3x))
    ]


def test_cost_boundaries() -> None:
    kw = {"reference_bps": 5.0, "reference_is_assumption": False}
    assert assess_costs(rows=_rows(50.0, 10.0), **kw).status == "PASS"
    assert assess_costs(rows=_rows(50.0, 0.0), **kw).status == "WEAK"
    assert assess_costs(rows=_rows(0.0, -50.0), **kw).status == "FAIL"
    assert assess_costs(rows=None, **kw).status == "NOT_MEASURED"
    assumed = assess_costs(rows=_rows(50.0, 10.0), reference_bps=10.0, reference_is_assumption=True)
    assert "assumed" in assumed.inputs["reference_bps_per_side"]["note"]


@pytest.mark.parametrize(
    ("oos", "gap", "expected"),
    [
        (0.5, 1.0, "PASS"),
        (0.49, 0.0, "WEAK"),
        (0.6, 1.01, "WEAK"),
        (0.0, 0.0, "FAIL"),
        (-0.3, 2.0, "FAIL"),
    ],
)
def test_out_of_sample_boundaries(oos: float, gap: float, expected: str) -> None:
    assert (
        assess_out_of_sample(oos_sharpe=oos, gap=gap, not_measured_reason=None).status == expected
    )


def test_out_of_sample_not_measured() -> None:
    dim = assess_out_of_sample(oos_sharpe=None, gap=None, not_measured_reason="no oos")
    assert dim.status == "NOT_MEASURED"
    assert dim.reasons == ["no oos"]


def test_data_quality_uses_severity() -> None:
    assert assess_data_quality([]).status == "PASS"
    assert assess_data_quality([RedFlag("X", "WARN", "")]).status == "WEAK"
    assert assess_data_quality([RedFlag("X", "WARN", ""), RedFlag("Y", "FAIL", "")]).status == (
        "FAIL"
    )


def test_benchmark_boundaries() -> None:
    kw = {"applicable": True, "not_measured_reason": None}
    assert (
        assess_benchmark(excess_return=0.1, drawdown_ratio=1.0, information_ratio=0.2, **kw).status
        == "PASS"
    )
    assert (
        assess_benchmark(excess_return=0.1, drawdown_ratio=1.5, information_ratio=0.2, **kw).status
        == "WEAK"
    )
    assert (
        assess_benchmark(excess_return=0.0, drawdown_ratio=0.5, information_ratio=0.2, **kw).status
        == "FAIL"
    )
    assert (
        assess_benchmark(
            applicable=False,
            excess_return=None,
            drawdown_ratio=None,
            information_ratio=None,
            not_measured_reason=None,
        ).status
        == "NOT_APPLICABLE"
    )
    assert (
        assess_benchmark(
            applicable=True,
            excess_return=None,
            drawdown_ratio=None,
            information_ratio=None,
            not_measured_reason="none",
        ).status
        == "NOT_MEASURED"
    )


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ({}, "A"),
        ({BENCHMARK: "NOT_APPLICABLE"}, "A"),
        ({COSTS: "NOT_MEASURED"}, "B"),
        ({OUT_OF_SAMPLE: "WEAK"}, "B"),
        ({BENCHMARK: "NOT_MEASURED"}, "B"),
        ({DATA_QUALITY: "WEAK"}, "B"),
        ({STATISTICAL: "WEAK"}, "C"),
        ({MULTIPLICITY: "WEAK"}, "C"),
        ({COSTS: "FAIL"}, "C"),
        ({BENCHMARK: "FAIL"}, "C"),
        ({STATISTICAL: "FAIL"}, "D"),
        ({DATA_QUALITY: "FAIL"}, "D"),
        ({COSTS: "FAIL", OUT_OF_SAMPLE: "FAIL"}, "D"),
        ({STATISTICAL: "NOT_MEASURED", MULTIPLICITY: "NOT_MEASURED"}, "C"),
    ],
)
def test_overall_class_table(statuses: dict[str, str], expected: str) -> None:
    assert overall_class(_dims(**statuses)) == expected


@pytest.mark.parametrize("locale", ["es", "en"])
@pytest.mark.parametrize("overall", ["A", "B", "C", "D"])
def test_summary_is_free_of_profit_claims(locale: str, overall: str) -> None:
    for status in ("PASS", "WEAK", "FAIL", "NOT_MEASURED"):
        dims = _dims(
            **{name: status for name in DIMENSION_ORDER if name != BENCHMARK},
            **{BENCHMARK: "NOT_APPLICABLE"},
        )
        for dim in dims:
            dim.reasons = ["motivo de prueba"]
        text = summary(dims, overall, locale=locale, trials=7)  # type: ignore[arg-type]
        assert find_claims(text) == []
        if status != "NOT_MEASURED":
            assert "7" in text
