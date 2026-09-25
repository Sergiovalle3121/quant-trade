"""What a buyer reading a real MT5 report noticed (GBPUSD, 59 trades):
the platform's open-trade drawdown, costs in pips, one Sharpe, plain words."""

from __future__ import annotations

from dataclasses import replace
from html import escape

import pytest

from quant_trade.audit.engine import fx_pair, platform_equity_drawdown, run_audit
from quant_trade.audit.guard import find_claims
from quant_trade.audit.redflags import annualised_sharpe
from quant_trade.audit.report import LABELS, render_html
from quant_trade.audit.sample import synthetic_mt5_report
from quant_trade.audit.schema import DeclaredMetadata, build_inputs

DEEP = {
    "declared_equity_drawdown_maximal": "1 279.20 (38.80%)",
    "declared_equity_drawdown_relative": "40.51% (1 027.00)",
}


@pytest.mark.parametrize(
    ("symbols", "meta", "pair"),
    [
        (["GBPUSD.m", "GBPUSD.m"], {}, "GBPUSD"),
        ([], {"symbol": "usdjpy"}, "USDJPY"),
        (["EURUSD", "GBPUSD"], {}, None),
        (["XAUUSD"], {}, None),
        (["US30"], {}, None),
    ],
)
def test_fx_pair(symbols: list[str], meta: dict[str, str], pair: str | None) -> None:
    assert fx_pair(symbols, meta) == pair


def test_platform_equity_drawdown_takes_the_deepest_percentage() -> None:
    assert platform_equity_drawdown(DEEP) == pytest.approx(0.4051)
    assert platform_equity_drawdown({"declared_equity_drawdown_maximal": "12,5 %"}) == 0.125
    assert platform_equity_drawdown({}) is None
    assert platform_equity_drawdown({"declared_equity_drawdown_maximal": "0.00 (0.00%)"}) is None


def _audit(metadata: dict[str, str] | None = None, **declared: object):  # type: ignore[no-untyped-def]
    inputs = build_inputs(
        None,
        DeclaredMetadata(**declared),
        report_bytes=synthetic_mt5_report(200),
        report_filename="ReportTester.html",
    )
    if metadata is not None:
        inputs = replace(inputs, report_metadata={**inputs.report_metadata, **metadata})
    return run_audit(inputs, bootstrap_samples=100, risk_samples=200, challenge_samples=200)


def test_one_sharpe_everywhere() -> None:
    result = _audit()
    data = result.model_dump() if hasattr(result, "model_dump") else result.to_dict()
    headline = data["performance"]["sharpe"]["value"]
    inputs_returns = build_inputs(
        None,
        DeclaredMetadata(),
        report_bytes=synthetic_mt5_report(200),
        report_filename="ReportTester.html",
    )
    expected = annualised_sharpe(inputs_returns.equity.returns, inputs_returns.periods_per_year)
    assert headline == pytest.approx(expected)


@pytest.mark.parametrize("locale", ["es", "en"])
def test_a_deeper_platform_drawdown_is_shown_beside_the_balance_one(locale: str) -> None:
    result = _audit(DEEP)
    page = render_html(result, watermark=False, locale=locale)
    labels = LABELS[locale]
    assert escape(labels["kpi_dd_platform"]) in page
    assert "-40.5%" in page
    # The prop-firm simulator's 10 % total loss is already crossed by open losses.
    assert escape(labels["open_loss_badge"]) in page
    assert find_claims(page) == []


def test_no_platform_line_without_the_figure() -> None:
    page = render_html(_audit(), watermark=False, locale="es")
    assert escape(LABELS["es"]["kpi_dd_platform"]) not in page
    assert escape(LABELS["es"]["open_loss_badge"]) not in page


@pytest.mark.parametrize("locale", ["es", "en"])
def test_costs_are_also_given_in_pips_on_a_currency_pair(locale: str) -> None:
    result = _audit()
    data = result.model_dump() if hasattr(result, "model_dump") else result.to_dict()
    costs = data["costs"]
    assert costs["pip_symbol"] == "EURUSD"
    bps, pips = costs["break_even_bps"]["value"], costs["break_even_pips"]["value"]
    # At about 1.1, one basis point is about 1.1 pips.
    assert 0.9 * bps < pips < 1.3 * bps
    page = render_html(result, watermark=False, locale=locale)
    assert " pips" in page
    assert "EURUSD" in page
    if locale == "es":
        assert "intento(s)" not in page
        assert "per side on" not in page and "in [" not in page
        assert ">commission<" not in page


def test_the_weak_multiplicity_reason_reads_as_a_sentence() -> None:
    from quant_trade.audit.verdict import Thresholds  # noqa: F401

    result = _audit(trials=1)
    data = result.model_dump() if hasattr(result, "model_dump") else result.to_dict()
    for dim in data["verdict"]["dimensions"]:
        for reason in dim.get("reasons_es", []) + dim.get("reasons", []):
            assert "in [" not in reason
