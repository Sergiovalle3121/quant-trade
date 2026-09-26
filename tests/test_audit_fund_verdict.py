"""A fund's track record in the verdict and the plan: its own index, no per-side
cost, and the questions a manager can answer. Offline."""

from __future__ import annotations

from html import escape

import numpy as np
import pandas as pd
import pytest

from quant_trade.audit.engine import FILE_BENCHMARK_NOTE, run_audit
from quant_trade.audit.guard import assert_report_clean, find_claims
from quant_trade.audit.i18n import untranslated
from quant_trade.audit.plan import FUND_TITLES, improvement_plan
from quant_trade.audit.report import render
from quant_trade.audit.schema import DeclaredMetadata, build_inputs
from quant_trade.audit.verdict import _TEXT, FUND_OOS_REASON, MEANING


def _dated(fund: np.ndarray, index: np.ndarray | None = None) -> bytes:
    stamps = pd.date_range("2016-01-31", periods=len(fund), freq="ME")
    if index is None:
        rows = [f"{t.date()},{f:.6f}" for t, f in zip(stamps, fund, strict=True)]
        return ("date,return\n" + "\n".join(rows) + "\n").encode()
    rows = [f"{t.date()},{f:.6f},{b:.6f}" for t, f, b in zip(stamps, fund, index, strict=True)]
    return ("date,return,Benchmark\n" + "\n".join(rows) + "\n").encode()


def _pair(n: int = 96, seed: int = 11, edge: float = 0.002) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    index = rng.normal(0.006, 0.035, n)
    return 0.9 * index + rng.normal(edge, 0.01, n), index


def _run(data: bytes, locale: str = "es", **declared: object) -> object:
    inputs = build_inputs(data, DeclaredMetadata(locale=locale, **declared))  # type: ignore[arg-type]
    return run_audit(inputs, bootstrap_samples=200)


def _status(result: object) -> dict[str, str]:
    return {d.name: d.status for d in result.verdict.dimensions}  # type: ignore[attr-defined]


def test_a_fund_that_trails_its_own_index_fails_the_benchmark() -> None:
    fund, index = _pair(edge=-0.004)
    result = _run(_dated(fund, index))
    assert _status(result)["benchmark"] == "FAIL"
    bench = result.benchmark  # type: ignore[attr-defined]
    assert bench["source"] == "file" and bench["excess_return"]["value"] < 0
    assert bench["overlap_share"]["note"] == FILE_BENCHMARK_NOTE
    data = result.model_dump(mode="json")  # type: ignore[attr-defined]
    steps = {step.dimension: step for step in improvement_plan(data, "es")}
    assert "índice que trae el propio archivo" in steps["benchmark"].finding
    assert untranslated(data) == []


def test_an_uploaded_benchmark_wins_and_a_declared_none_still_counts() -> None:
    fund, index = _pair()
    stamps = pd.date_range("2015-12-31", periods=len(index) + 1, freq="ME")
    levels = np.concatenate([[100.0], 100 * np.cumprod(1 + index * 0.5)])
    upload = (
        "date,close\n"
        + "\n".join(f"{t.date()},{v:.6f}" for t, v in zip(stamps, levels, strict=True))
        + "\n"
    ).encode()
    inputs = build_inputs(
        _dated(fund, index), DeclaredMetadata(locale="es"), benchmark_bytes=upload
    )
    uploaded = run_audit(inputs, bootstrap_samples=200)
    assert uploaded.benchmark["status"] == "MEASURED" and "source" not in uploaded.benchmark
    none = _run(_dated(fund, index), benchmark_applicable=False)
    assert _status(none)["benchmark"] == "NOT_APPLICABLE"


def test_an_index_with_a_missing_month_is_not_used() -> None:
    fund, index = _pair()
    data = _dated(fund, index).decode().splitlines()
    data[20] = data[20].rsplit(",", 1)[0] + ","
    result = _run(("\n".join(data) + "\n").encode())
    assert _status(result)["benchmark"] == "NOT_MEASURED"
    assert "source" not in result.benchmark  # type: ignore[attr-defined]


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_a_fund_record_reads_as_a_fund_in_the_verdict_and_the_plan(locale: str) -> None:
    fund, _ = _pair()
    result = _run(_dated(fund), locale, trials_declared=False)
    flags = {flag["code"] for flag in result.red_flags}  # type: ignore[attr-defined]
    assert "ZERO_DECLARED_COSTS" not in flags
    assert result.holdout["reason"] == FUND_OOS_REASON  # type: ignore[attr-defined]
    data = result.model_dump(mode="json")  # type: ignore[attr-defined]
    assert data["fund"]["track_record"] is True
    steps = {step.dimension: step for step in improvement_plan(data, locale)}
    oos = steps["out_of_sample"]
    assert oos.title == FUND_TITLES.get(locale, FUND_TITLES["en"])["out_of_sample"] or (
        locale == "pt" and "processo" in oos.title
    )
    words = {"es": "gestor", "en": "manager", "pt": "gestor"}[locale]
    assert words in oos.finding and words in " ".join(oos.actions)
    costs = steps["costs"]
    assert "MT5" not in " ".join(costs.actions) and words in " ".join(costs.actions)
    html, _ = render(result, watermark=False)  # type: ignore[arg-type]
    assert_report_clean(html)
    assert escape(MEANING[locale]["out_of_sample.NOT_MEASURED.fund"]) in html
    summary = result.verdict.summary  # type: ignore[attr-defined]
    if locale == "es":
        assert "fondos o estrategias" in summary and "configuraciones" not in summary
    assert untranslated(data) == []


def test_a_backtest_keeps_its_own_wording() -> None:
    rng = np.random.default_rng(2)
    days = pd.bdate_range("2021-01-04", periods=400)
    levels = 10_000 * np.cumprod(1 + rng.normal(0.0005, 0.01, len(days)))
    body = "timestamp,equity\n" + "\n".join(
        f"{t.date()},{v:.2f}" for t, v in zip(days, levels, strict=True)
    )
    result = _run((body + "\n").encode())
    assert result.holdout["reason"] == "no out-of-sample start declared"  # type: ignore[attr-defined]
    assert "ZERO_DECLARED_COSTS" in {f["code"] for f in result.red_flags}  # type: ignore[attr-defined]
    assert "configuraciones" in result.verdict.summary  # type: ignore[attr-defined]


def test_new_fund_texts_make_no_claims() -> None:
    for locale in ("es", "en", "pt"):
        for key, text in {**MEANING[locale], **_TEXT[locale]}.items():
            if key.endswith(".fund"):
                assert find_claims(text) == [], (locale, key)
        for text in FUND_TITLES.get(locale, {}).values():
            assert find_claims(text) == []


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_no_plan_step_asks_a_fund_for_robot_files(locale: str) -> None:
    rng = np.random.default_rng(4)
    for fund in (_pair()[0], rng.normal(-0.004, 0.03, 60), rng.normal(0.002, 0.03, 60)):
        result = _run(_dated(fund), locale, trials=40)
        data = result.model_dump(mode="json")  # type: ignore[attr-defined]
        # The history step (how much more record is needed) has its own fund wording.
        text = " ".join(
            " ".join([step.title, step.finding, *step.actions])
            for step in improvement_plan(data, locale)
            if step.dimension != "statistical_significance"
        )
        for word in ("MT5", "EA ", "XML", "coste por lado", "cost per side", "optimiza", "optimis"):
            assert word not in text, (locale, word)
        assert_report_clean(render(result, watermark=False)[0])  # type: ignore[arg-type]


def test_a_failing_fund_is_called_a_fund_in_the_summary() -> None:
    rng = np.random.default_rng(9)
    result = _run(_dated(rng.normal(-0.01, 0.03, 60)))
    overall = result.verdict.overall  # type: ignore[attr-defined]
    assert overall in {"C", "D"}
    first = _TEXT["es"][f"{overall}.fund"]
    assert result.verdict.summary.startswith(first)  # type: ignore[attr-defined]
    assert "backtest" not in first
