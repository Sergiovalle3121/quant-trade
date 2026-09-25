"""What data a MetaTrader backtest ran on: tick model, data quality, window.

The public fixtures are edited in memory to reproduce what buyers are warned
about: a coarse modelling mode, a patchy price history, and a header that
does not fit its own model or its own trades. Offline and deterministic.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from quant_trade.audit.engine import run_audit
from quant_trade.audit.guard import assert_report_clean
from quant_trade.audit.i18n import untranslated
from quant_trade.audit.importers import MT4_STATEMENT_HTML
from quant_trade.audit.report import render
from quant_trade.audit.schema import DeclaredMetadata, build_inputs
from quant_trade.audit.testdata import data_quality, review_test_data, stated_window, tick_model

FIXTURES = Path(__file__).parent / "fixtures" / "audit_imports"
MT4 = (FIXTURES / "mt4_tester.htm").read_text(encoding="utf-8")
MT5 = (FIXTURES / "mt5_tester.html").read_text(encoding="utf-8")
EVERY_TICK = (
    "Every tick (the most precise method based on all available least timeframes to generate "
    "each tick)"
)
QUALITY = "<td align=right>90.00%</td>"
MT4_WINDOW = "(2024.01.01 - 2024.01.06)"
NEW_FLAGS = {"COARSE_TICK_MODEL", "TEST_DATA_QUALITY_LOW", "REPORT_HEADER_MISMATCH"}


def _audit(text: str, name: str, locale: str = "es"):  # type: ignore[no-untyped-def]
    inputs = build_inputs(
        None,
        DeclaredMetadata(locale=locale),
        report_bytes=text.encode("utf-8"),
        report_filename=name,
    )
    return run_audit(inputs, bootstrap_samples=200)


def _mt4(*, model: str = EVERY_TICK, quality: str = "90.00%", window: str = MT4_WINDOW):  # type: ignore[no-untyped-def]
    text = (
        MT4.replace(EVERY_TICK, model)
        .replace(QUALITY, f"<td align=right>{quality}</td>")
        .replace(MT4_WINDOW, window)
    )
    return _audit(text, "StrategyTester.htm")


def _flags(result) -> dict[str, list[str]]:  # type: ignore[no-untyped-def]
    found: dict[str, list[str]] = {}
    for flag in result.red_flags:
        found.setdefault(flag["code"], []).append(flag["severity"])
    return found


def test_header_parsers() -> None:
    assert tick_model(EVERY_TICK) == "every tick"
    assert tick_model("Control points (a quick method)") == "control points"
    assert tick_model("Только цены открытия") == "open prices only"
    assert tick_model("something else") is None
    assert data_quality("90.00%") == pytest.approx(0.9)
    assert data_quality("100% real ticks") == pytest.approx(1.0)
    assert data_quality("n/a") is None
    assert stated_window("1 Hour (H1)  2024.01.02 00:00 - 2024.01.05 23:00    " + MT4_WINDOW) == (
        date(2024, 1, 1),
        date(2024, 1, 6),
    )
    assert stated_window("H1 (2024.01.01 - 2024.01.09)") == (date(2024, 1, 1), date(2024, 1, 9))
    assert stated_window("H1") is None


def test_clean_mt4_report_is_described_without_flags() -> None:
    result = _mt4()
    review = result.test_data
    assert review is not None and review["status"] == "MEASURED"
    assert review["tick_model"] == {
        "value": "every tick",
        "evidence": "DECLARED",
        "note": "the tester's modelling mode, as printed in the report header",
    }
    assert review["data_quality"]["value"] == pytest.approx(0.9)
    assert review["trades_outside_window"]["evidence"] == "MEASURED"
    assert review["trades_outside_window"]["value"] == 0
    assert review["tester_spread"]["value"] == "Current (12)"
    assert review["clean"] is True
    assert not set(_flags(result)) & NEW_FLAGS


def test_mt5_real_ticks_are_recognised() -> None:
    result = _audit(MT5, "ReportTester.html")
    review = result.test_data
    assert review is not None and review["tick_model"]["value"] == "real ticks"
    assert review["data_quality"]["value"] == pytest.approx(1.0)
    assert review["clean"] is True


@pytest.mark.parametrize(
    ("model", "quality"),
    [("Control points (a quick method)", "25.00%"), ("Open prices only (fastest)", "n/a")],
)
def test_coarse_model_is_a_warning(model: str, quality: str) -> None:
    flags = _flags(_mt4(model=model, quality=quality))
    assert flags["COARSE_TICK_MODEL"] == ["WARN"]
    assert "TEST_DATA_QUALITY_LOW" not in flags
    assert "REPORT_HEADER_MISMATCH" not in flags


@pytest.mark.parametrize(("quality", "severity"), [("72.00%", "WARN"), ("25.00%", "FAIL")])
def test_patchy_history_under_every_tick(quality: str, severity: str) -> None:
    result = _mt4(quality=quality)
    assert _flags(result)["TEST_DATA_QUALITY_LOW"] == [severity]
    codes = {question["code"] for question in result.vendor_questions}
    assert "modelling" in codes


def test_mt5_low_history_quality() -> None:
    result = _audit(MT5.replace("100% real ticks", "61%"), "ReportTester.html")
    assert _flags(result)["TEST_DATA_QUALITY_LOW"] == ["WARN"]
    assert result.test_data is not None and result.test_data["tick_model"]["value"] is None


def test_high_quality_with_a_coarse_model_does_not_add_up() -> None:
    result = _mt4(model="Control points (a quick method)", quality="99.00%")
    flags = _flags(result)
    assert flags["REPORT_HEADER_MISMATCH"] == ["WARN"]
    assert flags["COARSE_TICK_MODEL"] == ["WARN"]
    assert "original_file" in {question["code"] for question in result.vendor_questions}


def test_trades_outside_the_stated_window_do_not_add_up() -> None:
    result = _mt4(window="(2023.06.01 - 2023.06.30)")
    review = result.test_data
    assert review is not None and review["trades_outside_window"]["value"] > 0
    assert _flags(result)["REPORT_HEADER_MISMATCH"] == ["WARN"]
    assert result.verdict.overall != "A"


@pytest.mark.parametrize("locale", ["es", "en"])
def test_section_renders_clean_in_both_languages(locale: str) -> None:
    text = (
        MT4.replace(EVERY_TICK, "Control points (a quick method)")
        .replace(QUALITY, "<td align=right>99.00%</td>")
        .replace(MT4_WINDOW, "(2023.06.01 - 2023.06.30)")
    )
    result = _audit(text, "StrategyTester.htm", locale)
    html, _ = render(result, watermark=False)
    assert_report_clean(html)
    assert (
        "Con qué datos se hizo la prueba" if locale == "es" else "What data the test ran on"
    ) in (html)
    assert ("Puntos de control" if locale == "es" else "Control points") in html
    assert untranslated(result.model_dump(mode="json")) == []


def test_account_histories_are_not_reviewed() -> None:
    review, flags = review_test_data(source_format=MT4_STATEMENT_HTML, metadata={}, trades=None)
    assert review["status"] == "NOT_MEASURED" and flags == []
