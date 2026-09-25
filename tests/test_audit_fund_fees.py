"""What common yearly fees would take from a fund record not declared net. Offline."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_trade.audit.engine import run_audit
from quant_trade.audit.fund import FEE_RATES, fee_drag
from quant_trade.audit.guard import assert_report_clean, find_claims
from quant_trade.audit.i18n import untranslated
from quant_trade.audit.report import LABELS, render
from quant_trade.audit.schema import DeclaredMetadata, build_inputs

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _series(values: np.ndarray) -> pd.Series:
    stamps = pd.date_range("2015-01-31", periods=len(values), freq="ME", tz="UTC")
    return pd.Series(values, index=stamps)


def test_a_fee_comes_off_every_month() -> None:
    values = np.full(60, 0.01)
    fees = fee_drag(_series(values))
    assert [row["rate"] for row in fees["rows"]] == list(FEE_RATES)
    gross = 1.01**12 - 1
    assert fees["gross_cagr"]["value"] == pytest.approx(gross)
    assert fees["gross_growth"]["value"] == pytest.approx(1.01**60 - 1)
    for row in fees["rows"]:
        assert row["cagr"]["value"] == pytest.approx((1 + gross) / (1 + row["rate"]) - 1)
    assert "break_even" not in fees


def test_break_even_fee_against_the_benchmark() -> None:
    comparison = {
        "status": "MEASURED",
        "fund_cagr": {"value": 0.08},
        "index_cagr": {"value": 0.06},
    }
    fees = fee_drag(_series(np.full(36, 0.006)), comparison)
    assert fees["break_even"]["value"] == pytest.approx(1.08 / 1.06 - 1)


def test_too_short_is_not_measured() -> None:
    assert fee_drag(_series(np.full(12, 0.01)))["status"] == "NOT_MEASURED"


def _grid(values: np.ndarray, bench: np.ndarray | None = None) -> bytes:
    lines = ["Year," + ",".join(MONTHS)]
    for y in range(len(values) // 12):
        cells = [f"{v * 100:.2f}%" for v in values[12 * y : 12 * y + 12]]
        lines.append(",".join([str(2015 + y), *cells]))
        if bench is not None:
            cells = [f"{v * 100:.2f}%" for v in bench[12 * y : 12 * y + 12]]
            lines.append(",".join(["Benchmark", *cells]))
    return ("\n".join(lines) + "\n").encode()


@pytest.mark.parametrize("locale", ["es", "en"])
def test_the_fund_section_shows_the_fee_table(locale: str) -> None:
    rng = np.random.default_rng(5)
    fund = rng.normal(0.008, 0.03, 72)
    bench = fund - 0.001 + rng.normal(0, 0.004, 72)
    result = run_audit(
        build_inputs(_grid(fund, bench), DeclaredMetadata(locale=locale)), bootstrap_samples=200
    )
    assert result.fund is not None and result.fund["fees"]["status"] == "MEASURED"
    assert "break_even" in result.fund["fees"]
    html, _ = render(result, watermark=False)
    assert_report_clean(html)
    labels = LABELS[locale]
    assert labels["fund_fees"].replace("'", "&#x27;") in html
    assert "20 %" in labels["fund_fees_management"]
    assert labels["fund_fees_management"].split(".")[0] in html
    assert untranslated(result.model_dump(mode="json")) == []
    keys = ("fund_fees", "fund_fees_intro", "fund_fees_management")
    for key in (*keys, "fund_fees_break_even", "fund_fees_behind"):
        assert find_claims(labels[key]) == [], key


def test_declared_net_of_fees_shows_no_fee_table() -> None:
    fund = np.random.default_rng(5).normal(0.008, 0.03, 48)
    result = run_audit(
        build_inputs(_grid(fund), DeclaredMetadata(locale="es", net_of_fees=True)),
        bootstrap_samples=200,
    )
    assert result.fund is not None and "fees" not in result.fund
    html, _ = render(result, watermark=False)
    assert LABELS["es"]["fund_fees"] not in html


@pytest.mark.parametrize(
    ("break_even", "words"),
    [(0.0, "igual o por debajo"), (-0.01, "igual o por debajo"), (0.00038, "0.04 %")],
)
def test_break_even_wording_at_the_edges(break_even: float, words: str) -> None:
    from quant_trade.audit.report import _fund_fees_html

    fees = fee_drag(_series(np.full(36, 0.006)))
    fees["break_even"] = {"value": break_even}
    assert words in _fund_fees_html(fees, LABELS["es"])
