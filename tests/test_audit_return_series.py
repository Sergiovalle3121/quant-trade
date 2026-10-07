"""Synthetic institutional period tables: declared units, complete measured returns."""

from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest

from quant_trade.audit.engine import run_audit
from quant_trade.audit.fund import monthly_returns
from quant_trade.audit.guard import find_claims
from quant_trade.audit.importers import import_return_series, is_return_series
from quant_trade.audit.return_series import (
    ERRORS,
    ReturnSeriesError,
    frame_returns,
    infer_return_frequency,
    return_performance,
)
from quant_trade.audit.schema import DeclaredMetadata, ParseError, build_inputs


def _csv(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False).encode("utf-8")


def _table(frequency: str, count: int = 36) -> pd.DataFrame:
    # The first loss must affect the measured total and drawdown.
    values = np.resize(np.array([-0.08, 0.012, 0.029, -0.006, 0.011, 0.063]), count)
    return pd.DataFrame(
        {
            "date": pd.date_range("2020-01-01", periods=count, freq=frequency).strftime("%Y-%m-%d"),
            "return": values,
        }
    )


@pytest.fixture
def monthly_table() -> pd.DataFrame:
    return _table("ME")


@pytest.fixture
def weekly_table() -> pd.DataFrame:
    return _table("W-FRI", 104)


@pytest.mark.parametrize(
    ("frequency", "expected", "ppy"),
    [("B", "daily", 252), ("W-FRI", "weekly", 52), ("ME", "monthly", 12)],
)
def test_inference_uses_named_period_frequency(frequency: str, expected: str, ppy: int) -> None:
    frame = _table(frequency)
    series = import_return_series(_csv(frame))
    assert infer_return_frequency(series.frame["timestamp"]) == expected
    assert series.return_metadata["frequency_label"] == expected
    assert series.return_metadata["periods_per_year"] == ppy
    assert series.return_metadata["frequency_confirmed"] is False


def test_return_import_keeps_exact_dates_and_first_loss(monthly_table: pd.DataFrame) -> None:
    data = _csv(monthly_table)
    assert is_return_series(data)
    series = import_return_series(data)
    assert series.source == "returns"
    assert series.observations == len(monthly_table)
    assert series.raw_rows == len(monthly_table)
    assert (
        series.frame["timestamp"].tolist()
        == pd.to_datetime(monthly_table["date"], utc=True).tolist()
    )
    np.testing.assert_allclose(series.returns, monthly_table["return"])
    np.testing.assert_allclose(series.frame["equity"], (1 + monthly_table["return"]).cumprod())
    assert series.frame["ret"].iloc[0] == pytest.approx(-0.08)


@pytest.mark.parametrize(
    "encoding", ["fraction", "percent_sign", "percent_header", "percent_heuristic"]
)
def test_percent_and_fraction_read_the_same_returns(
    monthly_table: pd.DataFrame, encoding: str
) -> None:
    frame = monthly_table.copy()
    if encoding == "percent_sign":
        frame["return"] = frame["return"].map(lambda value: f"{value * 100:.8g}%")
    elif encoding in {"percent_header", "percent_heuristic"}:
        frame["return"] *= 100
        if encoding == "percent_header":
            frame = frame.rename(columns={"return": "return %"})
    series = import_return_series(_csv(frame))
    np.testing.assert_allclose(series.returns, monthly_table["return"])
    assert series.return_metadata["unit"] == ("fraction" if encoding == "fraction" else "percent")
    assert series.return_metadata["unit_confirmed"] is False


def test_ambiguous_small_percentage_can_be_confirmed(monthly_table: pd.DataFrame) -> None:
    frame = monthly_table.assign(**{"return": 0.1})
    series = import_return_series(_csv(frame), unit="percent", frequency="monthly")
    np.testing.assert_allclose(series.returns, np.full(len(frame), 0.001))
    assert series.return_metadata["unit_inferred"] == "fraction"
    assert series.return_metadata["unit"] == "percent"
    assert series.return_metadata["unit_confirmed"] is True
    assert series.return_metadata["frequency_confirmed"] is True


def test_xlsx_dates_and_returns_use_the_same_parser(monthly_table: pd.DataFrame) -> None:
    from test_audit_importers import xlsx

    dates = pd.to_datetime(monthly_table["date"])
    serials = (dates - pd.Timestamp("1899-12-30")).dt.days
    rows: list[list[object]] = [["date", "return"]]
    rows.extend(
        [
            [int(day), float(value)]
            for day, value in zip(serials, monthly_table["return"], strict=True)
        ]
    )
    workbook = xlsx({"Returns": rows})
    assert is_return_series(workbook)
    series = import_return_series(workbook)
    assert (
        series.frame["timestamp"].tolist()
        == pd.to_datetime(monthly_table["date"], utc=True).tolist()
    )
    np.testing.assert_allclose(series.returns, monthly_table["return"])
    assert series.return_metadata["periods_per_year"] == 12


def test_equity_column_keeps_existing_curve_precedence(monthly_table: pd.DataFrame) -> None:
    frame = monthly_table.assign(equity=(1 + monthly_table["return"]).cumprod())
    assert is_return_series(_csv(frame)) is False


def test_explicit_frequency_cannot_relabel_monthly_as_daily(monthly_table: pd.DataFrame) -> None:
    with pytest.raises(ParseError) as caught:
        import_return_series(_csv(monthly_table), frequency="daily")
    assert caught.value.code == "return_frequency_mismatch"


def test_irregular_frequency_requires_a_declaration() -> None:
    data = b"date,return\n2020-01-01,0.01\n2020-02-28,-0.02\n2020-07-31,0.03\n"
    with pytest.raises(ParseError) as caught:
        import_return_series(data)
    assert caught.value.code == "return_frequency_unknown"
    series = import_return_series(data, frequency="monthly")
    assert series.return_metadata["frequency_inferred"] is None
    assert series.return_metadata["periods_per_year"] == 12
    assert len(series.frame) == 3


@pytest.mark.parametrize(
    ("values", "unit", "code"),
    [
        (["1%", "0.01"], None, "return_unit_mixed"),
        (["1%", "2%"], "fraction", "return_unit_mismatch"),
        ([-1, 0.02], "fraction", "return_values"),
        ([0.02, 1e7], "fraction", "return_values"),
    ],
)
def test_damaged_units_and_impossible_returns_are_not_silently_repaired(
    values: list[object], unit: str | None, code: str
) -> None:
    data = _csv(pd.DataFrame({"date": ["2020-01-31", "2020-02-29"], "return": values}))
    with pytest.raises(ParseError) as caught:
        import_return_series(data, unit=unit)
    assert caught.value.code == code


def test_gross_and_net_are_retained_and_net_drives_the_audit(monthly_table: pd.DataFrame) -> None:
    frame = monthly_table.assign(
        gross_return=monthly_table["return"] + 0.002, net_return=monthly_table["return"]
    )
    frame["return"] = 0.2  # The explicit net column wins over a generic return.
    series = import_return_series(_csv(frame))
    assert series.return_metadata["basis"] == "net"
    assert series.return_metadata["gross_unit"] == "fraction"
    assert series.return_metadata["net_unit"] == "fraction"
    np.testing.assert_allclose(series.frame["gross_ret"], monthly_table["return"] + 0.002)
    np.testing.assert_allclose(series.frame["net_ret"], monthly_table["return"])
    np.testing.assert_allclose(series.returns, monthly_table["return"])


def test_gross_and_net_do_not_require_a_generic_return_column(monthly_table: pd.DataFrame) -> None:
    frame = monthly_table.rename(columns={"return": "net_return"})
    frame["gross_return"] = frame["net_return"] + 0.001
    assert is_return_series(_csv(frame))
    series = import_return_series(_csv(frame))
    assert series.return_metadata["basis"] == "net"
    assert set(series.frame.columns) >= {"gross_ret", "net_ret", "ret", "equity", "timestamp"}


def test_filtering_and_sorting_apply_to_gross_and_net_together(monthly_table: pd.DataFrame) -> None:
    frame = monthly_table.assign(
        gross_return=monthly_table["return"] + 0.002, net_return=monthly_table["return"]
    )
    frame.loc[2, "gross_return"] = np.nan
    shuffled = pd.concat([frame.iloc[::-1], frame.iloc[[0]]], ignore_index=True)
    series = import_return_series(_csv(shuffled), frequency="monthly")
    assert series.unparseable_rows == 1
    assert series.duplicate_timestamps == 1
    assert series.non_monotonic
    assert series.frame["timestamp"].is_monotonic_increasing
    np.testing.assert_allclose(series.frame["gross_ret"] - series.frame["net_ret"], 0.002)


def test_embedded_benchmark_keeps_its_first_return(monthly_table: pd.DataFrame) -> None:
    frame = monthly_table.assign(benchmark=monthly_table["return"] - 0.001)
    series = import_return_series(_csv(frame))
    assert series.benchmark is not None
    np.testing.assert_allclose(series.benchmark["ret"], frame["benchmark"])
    assert len(series.benchmark) == len(frame)


def test_missing_first_embedded_benchmark_return_is_not_invented(
    monthly_table: pd.DataFrame,
) -> None:
    frame = monthly_table.assign(benchmark=monthly_table["return"] / 2)
    frame.loc[0, "benchmark"] = np.nan
    result = run_audit(
        build_inputs(_csv(frame), DeclaredMetadata()),
        bootstrap_samples=20,
        risk_samples=20,
        challenge_samples=20,
    )
    assert result.benchmark["status"] == "NOT_MEASURED"
    assert "benchmark_total_return" not in result.benchmark


def test_embedded_benchmark_source_remains_declared(monthly_table: pd.DataFrame) -> None:
    frame = monthly_table.assign(benchmark=monthly_table["return"] / 2)
    result = run_audit(
        build_inputs(_csv(frame), DeclaredMetadata()),
        bootstrap_samples=20,
        risk_samples=20,
        challenge_samples=20,
    )
    assert result.benchmark["status"] == "MEASURED"
    assert result.benchmark["source"]["evidence"] == "DECLARED"
    assert result.benchmark["source"]["value"] == "embedded column"
    assert result.inputs["return_series"]["benchmark_source"]["evidence"] == "DECLARED"
    assert result.inputs["return_series"]["benchmark_source"]["value"] == "embedded column"


def test_gross_compounding_out_of_range_is_not_measured() -> None:
    frame = _table("ME", 72)
    frame = frame.assign(gross_return=1e6, net_return=frame["return"])
    result = run_audit(
        build_inputs(_csv(frame), DeclaredMetadata(return_unit="fraction")),
        bootstrap_samples=20,
        risk_samples=20,
        challenge_samples=20,
    )
    gross_total = result.inputs["return_series"]["gross"]["total_return"]
    assert gross_total["evidence"] == "NOT_MEASURED"
    assert gross_total["value"] is None
    assert result.performance["total_return"]["evidence"] == "MEASURED"
    json.dumps(result.model_dump(), allow_nan=False)


def test_complete_return_metrics_include_initial_loss_and_monthly_annualisation(
    monthly_table: pd.DataFrame,
) -> None:
    series = import_return_series(_csv(monthly_table))
    metrics = return_performance(series.frame, 12)
    expected = monthly_table["return"]
    assert metrics["total_return"] == pytest.approx(float((1 + expected).prod() - 1))
    assert metrics["sharpe"] == pytest.approx(
        float(expected.mean() / expected.std(ddof=1) * math.sqrt(12))
    )
    assert metrics["volatility"] == pytest.approx(float(expected.std(ddof=1) * math.sqrt(12)))
    curve = np.r_[1.0, (1 + expected).cumprod()]
    assert metrics["max_drawdown"] == pytest.approx(
        float((curve / np.maximum.accumulate(curve) - 1).min())
    )
    assert metrics["max_drawdown"] <= -0.08 + 1e-12
    assert metrics["cagr"] == pytest.approx(
        float((1 + expected).prod() ** (12 / len(expected)) - 1)
    )


def test_frame_returns_preserves_explicit_first_value_and_handles_plain_equity() -> None:
    frame = pd.DataFrame({"equity": [0.9, 0.99, 0.891], "ret": [-0.1, 0.1, -0.1]})
    np.testing.assert_allclose(frame_returns(frame), [-0.1, 0.1, -0.1])
    np.testing.assert_allclose(frame_returns(frame.drop(columns="ret")), [0.1, -0.1])


def test_fund_calendar_retains_first_supplied_month(monthly_table: pd.DataFrame) -> None:
    series = import_return_series(_csv(monthly_table))
    monthly = monthly_returns(series.frame)
    np.testing.assert_allclose(monthly, monthly_table["return"])
    assert monthly.index[0] == series.frame["timestamp"].iloc[0]


def test_fund_calendar_does_not_fill_a_missing_month(monthly_table: pd.DataFrame) -> None:
    frame = monthly_table.drop(index=2)
    series = import_return_series(_csv(frame), frequency="monthly")
    monthly = monthly_returns(series.frame)
    assert len(monthly) == len(frame)
    assert pd.Timestamp("2020-03-31", tz="UTC") not in monthly.index
    np.testing.assert_allclose(monthly, frame["return"])


def test_fund_counts_the_missing_month_without_a_dated_base(monthly_table: pd.DataFrame) -> None:
    frame = monthly_table.drop(index=2)
    result = run_audit(
        build_inputs(_csv(frame), DeclaredMetadata(return_frequency="monthly")),
        bootstrap_samples=20,
        risk_samples=20,
        challenge_samples=20,
    )
    assert result.fund is not None
    assert result.fund["status"] == "MEASURED"
    assert result.fund["months"]["value"] == len(frame)
    assert result.fund["missing_months"]["value"] == 1


@pytest.mark.parametrize("fixture_name,ppy", [("monthly_table", 12), ("weekly_table", 52)])
def test_engine_uses_full_series_and_declared_frequency(
    request: pytest.FixtureRequest, fixture_name: str, ppy: int
) -> None:
    frame = request.getfixturevalue(fixture_name)
    inputs = build_inputs(_csv(frame), DeclaredMetadata(trials=10))
    assert inputs.periods_per_year == ppy
    result = run_audit(inputs, bootstrap_samples=20, risk_samples=20, challenge_samples=20)
    json.dumps(result.model_dump(), allow_nan=False)
    expected = frame["return"]
    assert result.inputs["observations"]["value"] == len(frame)
    assert result.inputs["periods_per_year"]["value"] == ppy
    assert result.inputs["periods_per_year"]["evidence"] == "DECLARED"
    assert result.performance["sharpe"]["value"] == pytest.approx(
        float(expected.mean() / expected.std(ddof=1) * math.sqrt(ppy))
    )
    assert result.performance["sharpe"]["evidence"] == "MEASURED"
    assert result.luck is not None
    assert result.luck["status"] == "MEASURED"
    assert result.luck["sharpe"]["value"] == pytest.approx(result.performance["sharpe"]["value"])
    assert result.performance["total_return"]["value"] == pytest.approx(
        float((1 + expected).prod() - 1)
    )
    assert result.inputs["first_timestamp"].startswith(str(frame["date"].iloc[0]))


def test_benchmark_with_different_frequency_is_not_measured(
    monthly_table: pd.DataFrame, weekly_table: pd.DataFrame
) -> None:
    inputs = build_inputs(
        _csv(monthly_table), DeclaredMetadata(), benchmark_bytes=_csv(weekly_table)
    )
    result = run_audit(inputs, bootstrap_samples=20, risk_samples=20, challenge_samples=20)
    assert result.benchmark["status"] == "NOT_MEASURED"
    assert "frequen" in result.benchmark["reason"]
    dimension = next(item for item in result.verdict.dimensions if item.name == "benchmark")
    assert dimension.status == "NOT_MEASURED"


def test_daily_equity_and_daily_return_benchmark_have_matching_frequency() -> None:
    returns = _table("B", 100)
    equity = returns[["date"]].assign(equity=10_000 * (1 + returns["return"]).cumprod())
    inputs = build_inputs(_csv(equity), DeclaredMetadata(), benchmark_bytes=_csv(returns))
    assert inputs.equity.return_metadata == {}
    assert inputs.benchmark is not None
    assert inputs.benchmark.return_metadata["periods_per_year"] == 252
    assert inputs.periods_per_year != 252  # Legacy curves infer their observed density.
    result = run_audit(inputs, bootstrap_samples=20, risk_samples=20, challenge_samples=20)
    assert result.benchmark["status"] == "MEASURED"
    assert result.benchmark["strategy_frequency"]["value"] == "daily"
    assert result.benchmark["benchmark_frequency"]["value"] == "daily"


def test_declared_gross_net_difference_drives_cost_scenarios(monthly_table: pd.DataFrame) -> None:
    gross = monthly_table["return"] + 0.002
    net = monthly_table["return"]
    frame = monthly_table.assign(gross_return=gross, net_return=net)
    result = run_audit(
        build_inputs(_csv(frame), DeclaredMetadata()),
        bootstrap_samples=20,
        risk_samples=20,
        challenge_samples=20,
    )
    assert result.costs["kind"] == "period_returns"
    assert result.costs["status"] == "MEASURED"
    assert result.costs["reference_basis"]["evidence"] == "DECLARED"
    assert result.costs["periods_per_year"]["value"] == 12
    assert result.costs["periods_per_year"]["evidence"] == "DECLARED"
    for multiplier, scenario in enumerate(result.costs["rows"], start=1):
        expected = gross - multiplier * (gross - net)
        assert scenario["multiplier"]["value"] == multiplier
        assert scenario["multiplier"]["evidence"] == "DECLARED"
        assert scenario["total_return"]["value"] == pytest.approx(float((1 + expected).prod() - 1))
        assert scenario["total_return"]["evidence"] == "MEASURED"
    assert result.costs["rows"][0]["total_return"]["value"] == pytest.approx(
        result.performance["total_return"]["value"]
    )


def test_net_above_gross_is_not_a_measured_cost(monthly_table: pd.DataFrame) -> None:
    frame = monthly_table.assign(
        gross_return=monthly_table["return"] - 0.002,
        net_return=monthly_table["return"],
    )
    result = run_audit(
        build_inputs(_csv(frame), DeclaredMetadata()),
        bootstrap_samples=20,
        risk_samples=20,
        challenge_samples=20,
    )
    assert result.costs["status"] == "NOT_MEASURED"
    assert "net return exceeds gross return" in result.costs["reason"]
    assert result.costs["rows"] == []


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_all_new_parser_errors_pass_claim_guard(locale: str) -> None:
    for code in ERRORS:
        text = ReturnSeriesError(code).localized(locale)
        assert text == ERRORS[code][locale]
        assert find_claims(text) == [], (code, locale)
