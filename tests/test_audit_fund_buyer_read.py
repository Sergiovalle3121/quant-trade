"""A fund's monthly record reads as a fund, not a robot: its next steps, its
questions and its sections speak to a fund investor. An account history is
named as one, and the plan never counts centuries of missing history.
Offline and deterministic."""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime

import numpy as np
import pytest

from quant_trade.audit import report
from quant_trade.audit.account import ACCOUNT_FORMATS
from quant_trade.audit.analytics import vendor_questions
from quant_trade.audit.charts import TEXT as CHART_TEXT
from quant_trade.audit.engine import run_audit
from quant_trade.audit.guard import find_claims
from quant_trade.audit.plan import improvement_plan
from quant_trade.audit.schema import DeclaredMetadata, build_inputs

NOW = datetime(2026, 1, 1, tzinfo=UTC)
LOCALES = ("es", "en", "pt")
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
ROBOT = re.compile(r"\b(robot|robô|EA|backtest del mismo|backtest of the same)\b", re.IGNORECASE)


def _grid(years: int = 6, seed: int = 5) -> bytes:
    rng = np.random.default_rng(seed)
    index = rng.normal(0.007, 0.04, 12 * years)
    fund = 0.9 * index + rng.normal(0.002, 0.012, 12 * years)
    lines = [",".join(["Year", *MONTHS])]
    for y in range(years):
        chunk = slice(12 * y, 12 * y + 12)
        lines.append(",".join([str(2018 + y), *(f"{v * 100:.2f}%" for v in fund[chunk])]))
        lines.append(",".join(["Benchmark", *(f"{v * 100:.2f}%" for v in index[chunk])]))
    return ("\n".join(lines) + "\n").encode()


@pytest.fixture(scope="module")
def fund_data() -> dict:
    inputs = build_inputs(_grid(), DeclaredMetadata())
    result = run_audit(inputs, now=NOW, audit_id="fundread", bootstrap_samples=200)
    data = result.model_dump(mode="json")
    assert data["fund"]["track_record"] is True
    return data


def _text(page: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page)))


def _page(data: dict, locale: str) -> str:
    result = report.AuditResult.model_validate(data)
    return report.render_html(result, watermark=False, locale=locale)


def test_a_fund_gets_a_fund_investors_questions(fund_data: dict) -> None:
    codes = [q["code"] for q in fund_data["vendor_questions"]]
    assert codes == ["fund_net", "fund_same_record", "fund_other", "fund_admin"]
    for question in fund_data["vendor_questions"]:
        assert not ROBOT.search(question["es"]) and not ROBOT.search(question["en"])


def test_a_fund_asks_about_its_data_only_when_a_data_flag_says_so() -> None:
    plain = vendor_questions([], **_no_upload(), fund_record=True)
    flagged = vendor_questions(
        ["STALE_MARKS", "MARTINGALE_SIZING"], **_no_upload(), fund_record=True
    )
    assert "data_quality" not in [q["code"] for q in plain]
    assert [q["code"] for q in flagged][-1] == "data_quality"
    assert "martingale" not in [q["code"] for q in flagged]


def _no_upload() -> dict:
    return {
        "has_trades": False,
        "trials_measured": False,
        "has_out_of_sample": False,
        "has_costs": False,
        "balance_only": False,
    }


@pytest.mark.parametrize("locale", LOCALES)
def test_a_fund_report_speaks_to_a_fund_investor(fund_data: dict, locale: str) -> None:
    labels = report.LABELS[locale]
    shown = _text(_page(fund_data, locale))
    assert labels["next_intro_fund"] in shown
    assert labels["next_keep_fund"] in shown
    assert labels["next_intro"] not in shown
    assert labels["next_oos"] not in shown
    # Sections about trades or daily data a monthly fund record never has stay out.
    for key in ("trade_stats", "timing", "challenge", "stress_trades"):
        assert f"{labels[key]} " not in shown, key
    assert labels["title_fund"] in shown
    assert find_claims(shown) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_a_fund_shows_its_calendar_once(fund_data: dict, locale: str) -> None:
    page = _page(fund_data, locale)
    # The curve-built calendar would repeat the file's own, off by rounding.
    assert CHART_TEXT.get(locale, CHART_TEXT["en"])["monthly_desc"] not in html.unescape(page)


def test_a_backtest_keeps_its_robot_steps_and_sections() -> None:
    frame_bytes = _daily_curve()
    inputs = build_inputs(frame_bytes, DeclaredMetadata())
    data = run_audit(inputs, now=NOW, audit_id="btread", bootstrap_samples=200).model_dump(
        mode="json"
    )
    assert not (data.get("fund") or {}).get("track_record")
    labels = report.LABELS["es"]
    shown = _text(_page(data, "es"))
    assert labels["next_intro"] in shown
    assert labels["trade_stats"] in shown
    assert labels["title"] in shown


def _daily_curve() -> bytes:
    rng = np.random.default_rng(11)
    equity = 10_000 * np.cumprod(1 + rng.normal(0.0004, 0.01, 400))
    days = np.datetime64("2022-01-03") + np.arange(400)
    lines = ["timestamp,equity"] + [f"{d},{e:.2f}" for d, e in zip(days, equity, strict=True)]
    return ("\n".join(lines) + "\n").encode()


@pytest.mark.parametrize("locale", LOCALES)
def test_an_account_history_is_titled_as_one(locale: str) -> None:
    labels = report.LABELS[locale]
    account = {"inputs": {"source_format": sorted(ACCOUNT_FORMATS)[0]}}
    assert report._title(account, labels) == labels["title_account"]
    assert report._title({"inputs": {"source_format": "csv"}}, labels) == labels["title"]


@pytest.mark.parametrize("locale", LOCALES)
def test_the_plan_never_counts_centuries_of_missing_history(locale: str) -> None:
    rng = np.random.default_rng(2)
    days = np.datetime64("2024-01-01") + np.arange(120)
    equity = 10_000 * np.cumprod(1 + rng.normal(0.00005, 0.01, 120))
    lines = ["timestamp,equity"] + [f"{d},{e:.2f}" for d, e in zip(days, equity, strict=True)]
    inputs = build_inputs(("\n".join(lines) + "\n").encode(), DeclaredMetadata())
    data = run_audit(inputs, now=NOW, audit_id="plancap", bootstrap_samples=200).model_dump(
        mode="json"
    )
    sig = data["significance"]
    need = sig["min_track_record_length"]["value"]
    have = sig["observations"]["value"]
    steps = {s.dimension: s for s in improvement_plan(data, locale)}
    assert need > 10 * have
    finding = steps["statistical_significance"].finding
    assert "10" in finding
    assert not re.search(r"\d{3,} (años|years|anos)", finding)
    assert find_claims(finding) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_a_funds_plan_asks_for_the_managers_record_not_a_demo_account(
    fund_data: dict, locale: str
) -> None:
    steps = {s.dimension: s for s in improvement_plan(fund_data, locale)}
    if "statistical_significance" not in steps:
        pytest.skip("this record already passes significance")
    actions = " ".join(steps["statistical_significance"].actions)
    assert not re.search(r"demo|backtest|parámetros|parameters|parâmetros", actions)
    assert find_claims(actions) == []
