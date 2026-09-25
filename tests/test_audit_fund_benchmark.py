"""A fund against the benchmark its file carries or the customer uploads. Offline."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_trade.audit.engine import run_audit
from quant_trade.audit.fund import compare_with_benchmark, fund_review
from quant_trade.audit.guard import assert_report_clean, find_claims
from quant_trade.audit.i18n import untranslated
from quant_trade.audit.report import LABELS, render
from quant_trade.audit.schema import DeclaredMetadata, build_inputs, parse_equity_csv

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _pair(n: int = 60, seed: int = 3) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    index = rng.normal(0.007, 0.04, n)
    fund = 0.8 * index + rng.normal(0.001, 0.015, n)
    return fund, index


def _cells(values: np.ndarray) -> list[str]:
    return [f"{v * 100:.2f}%" for v in values]


def _labelled_grid(fund: np.ndarray, index: np.ndarray, layout: str) -> bytes:
    years = len(fund) // 12
    lines: list[str] = []
    if layout == "label":
        lines.append(",".join(["Series", "Year", *MONTHS]))
        for y in range(years):
            chunk = slice(12 * y, 12 * y + 12)
            lines.append(",".join(["Acme Fund", str(2019 + y), *_cells(fund[chunk])]))
            lines.append(",".join(["MSCI World", str(2019 + y), *_cells(index[chunk])]))
            lines.append(",".join(["Excess", str(2019 + y), *_cells(fund[chunk] - index[chunk])]))
    elif layout == "alternating":
        lines.append(",".join(["Year", *MONTHS]))
        for y in range(years):
            chunk = slice(12 * y, 12 * y + 12)
            lines.append(",".join([str(2019 + y), *_cells(fund[chunk])]))
            lines.append(",".join(["Benchmark", *_cells(index[chunk])]))
    else:  # two blocks, the benchmark's under its own heading
        lines.append(",".join(["Year", *MONTHS]))
        for y in range(years):
            lines.append(",".join([str(2019 + y), *_cells(fund[12 * y : 12 * y + 12])]))
        lines.append(",".join(["Benchmark", *[""] * 12]))
        for y in range(years):
            lines.append(",".join([str(2019 + y), *_cells(index[12 * y : 12 * y + 12])]))
    return ("\n".join(lines) + "\n").encode()


@pytest.mark.parametrize("layout", ["label", "alternating", "blocks"])
def test_a_factsheet_with_benchmark_rows_keeps_them_apart(layout: str) -> None:
    fund, index = _pair()
    series = parse_equity_csv(_labelled_grid(fund, index, layout))
    assert series.frame["ret"].dropna().to_numpy() == pytest.approx(fund, abs=5e-5)
    assert series.benchmark is not None
    assert series.benchmark["ret"].to_numpy() == pytest.approx(index, abs=5e-5)
    assert any("benchmark rows read from the table" in w for w in series.warnings)
    if layout == "label":
        assert any("5 row(s) of differences" in w for w in series.warnings)


def _dated(fund: np.ndarray, index: np.ndarray, *, column: str = "Benchmark") -> bytes:
    stamps = pd.date_range("2019-01-31", periods=len(fund), freq="ME")
    lines = [f"date,return,{column}"] + [
        f"{t.date()},{f:.6f},{b:.6f}" for t, f, b in zip(stamps, fund, index, strict=True)
    ]
    return ("\n".join(lines) + "\n").encode()


def test_a_dated_file_with_a_benchmark_column() -> None:
    fund, index = _pair()
    series = parse_equity_csv(_dated(fund, index))
    assert series.benchmark is not None
    assert series.benchmark["ret"].to_numpy() == pytest.approx(index, abs=1e-6)
    assert any("benchmark column 'benchmark' read" in w for w in series.warnings)


def test_a_row_number_called_index_is_not_a_benchmark() -> None:
    fund, _ = _pair()
    series = parse_equity_csv(_dated(fund, np.arange(len(fund), dtype=float), column="index"))
    assert series.benchmark is None


def _months(values: np.ndarray) -> pd.Series:
    stamps = pd.date_range("2019-01-31", periods=len(values), freq="ME", tz="UTC")
    return pd.Series(values, index=stamps)


def test_the_comparison_figures() -> None:
    fund, index = _pair(120)
    review = compare_with_benchmark(_months(fund), _months(index), "file")
    assert review["status"] == "MEASURED" and review["months"]["value"] == 120
    cagr = lambda r: float(np.prod(1 + r) ** (12 / len(r)) - 1)  # noqa: E731
    assert review["excess"]["value"] == pytest.approx(cagr(fund) - cagr(index))
    assert review["beat_share"]["value"] == pytest.approx(float((fund > index).mean()))
    assert review["beta"]["value"] == pytest.approx(0.8, abs=0.1)
    te = float(np.std(fund - index, ddof=1)) * np.sqrt(12)
    assert review["tracking_error"]["value"] == pytest.approx(te)
    up, down = review["up_capture"]["value"], review["down_capture"]["value"]
    assert 0.5 < up < 1.1 and 0.5 < down < 1.1


def test_an_index_hugger_and_a_laggard_are_found() -> None:
    _, index = _pair(60)
    hugger = index + np.random.default_rng(9).normal(-0.001, 0.003, 60)
    review = compare_with_benchmark(_months(hugger), _months(index), "file")
    assert "index_like" in review["findings"] and "trails" in review["findings"]


def test_worse_both_ways_is_found() -> None:
    _, index = _pair(60)
    fund = np.where(index > 0, 0.6 * index, 1.4 * index)
    review = compare_with_benchmark(_months(fund), _months(index), "file")
    assert "worse_both_ways" in review["findings"]
    assert review["up_capture"]["value"] < 1 < review["down_capture"]["value"]


def test_too_few_shared_months_is_not_measured() -> None:
    fund, index = _pair(60)
    review = compare_with_benchmark(_months(fund), _months(index[:20]), "file")
    assert review["status"] == "NOT_MEASURED" and "24 months shared" in review["reason"]


def test_every_benchmark_label_passes_the_guard() -> None:
    for labels in LABELS.values():
        for key, text in labels.items():
            if key.startswith("fund_bench"):
                assert find_claims(text) == [], text


@pytest.mark.parametrize("locale", ["es", "en"])
def test_the_section_shows_the_benchmark_and_the_class_does_not_move(locale: str) -> None:
    fund, index = _pair(72)
    with_bench = _labelled_grid(fund, index, "alternating")
    alone = (
        "\n".join(
            ["Year," + ",".join(MONTHS)]
            + [",".join([str(2019 + y), *_cells(fund[12 * y : 12 * y + 12])]) for y in range(6)]
        )
        + "\n"
    ).encode()
    a = run_audit(build_inputs(with_bench, DeclaredMetadata(locale=locale)), bootstrap_samples=200)
    b = run_audit(build_inputs(alone, DeclaredMetadata(locale=locale)), bootstrap_samples=200)
    assert a.fund is not None and a.fund["benchmark"]["status"] == "MEASURED"
    assert a.verdict.model_dump() == b.verdict.model_dump()
    assert [f["code"] for f in a.red_flags] == [f["code"] for f in b.red_flags]
    html, _ = render(a, watermark=False)
    assert_report_clean(html)
    assert LABELS[locale]["fund_bench"] in html
    assert ("esta comparación lo favorece" if locale == "es" else "comparison flatters it") in html
    assert untranslated(a.model_dump(mode="json")) == []


def test_an_uploaded_benchmark_file_is_used_for_a_fund() -> None:
    fund, index = _pair(60)
    alone = (
        "\n".join(
            ["Year," + ",".join(MONTHS)]
            + [",".join([str(2019 + y), *_cells(fund[12 * y : 12 * y + 12])]) for y in range(5)]
        )
        + "\n"
    ).encode()
    stamps = pd.date_range("2018-12-31", periods=61, freq="ME")
    levels = np.concatenate([[100.0], 100 * np.cumprod(1 + index)])
    bench = (
        "date,close\n"
        + "\n".join(f"{t.date()},{v:.6f}" for t, v in zip(stamps, levels, strict=True))
        + "\n"
    ).encode()
    result = run_audit(
        build_inputs(alone, DeclaredMetadata(locale="es"), benchmark_bytes=bench),
        bootstrap_samples=200,
    )
    assert result.fund is not None
    review = result.fund["benchmark"]
    assert review["status"] == "MEASURED" and review["source"] == "upload"
    assert review["months"]["value"] == 60
    html, _ = render(result, watermark=False)
    assert "archivo de benchmark que subiste" in html
    assert untranslated(result.model_dump(mode="json")) == []


def test_a_fund_without_a_benchmark_has_no_block() -> None:
    fund, _ = _pair(36)
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2018-12-31", periods=37, freq="ME", tz="UTC"),
            "equity": np.concatenate([[1.0], np.cumprod(1 + fund)]),
        }
    )
    assert "benchmark" not in fund_review(frame, 12.0)


def test_a_lone_index_column_is_never_taken_as_a_benchmark() -> None:
    from quant_trade.audit.schema import ParseError

    # As before this change: "index" alone is not a curve alias, so the file
    # is refused for its missing value column, never half-read as a benchmark.
    for column in ("index", "Indice", "referencia"):
        data = f"date,{column}\n2020-01-31,100\n2020-02-29,103\n2020-03-31,99\n".encode()
        with pytest.raises(ParseError) as caught:
            parse_equity_csv(data)
        assert caught.value.code == "missing_value"
    # Beside a named curve, the curve stays the curve.
    series = parse_equity_csv(
        b"date,nav,index\n2020-01-31,100,50\n2020-02-29,103,52\n2020-03-31,99,49\n"
    )
    assert series.source == "equity" and series.frame["equity"].iloc[-1] == 99
    assert series.benchmark is not None
    assert series.benchmark["ret"].to_numpy() == pytest.approx([0.04, 49 / 52 - 1])
