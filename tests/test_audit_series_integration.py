"""Complete periodic reports remain consistent and claim-safe in every locale."""

import json

import numpy as np
import pandas as pd
import pytest

from quant_trade.audit.engine import run_audit
from quant_trade.audit.guard import find_claims
from quant_trade.audit.i18n import untranslated
from quant_trade.audit.report import render_html
from quant_trade.audit.schema import DeclaredMetadata, build_inputs


@pytest.fixture(scope="module")
def periodic_result():
    values = np.resize([-0.08, 0.03, 0.01, -0.02, 0.02, 0.01], 36)
    table = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-31", periods=36, freq="ME"),
            "gross_return": values + 0.002,
            "net_return": values,
        }
    )
    benchmark = (
        table[["date"]].assign(return_value=values / 2).rename(columns={"return_value": "return"})
    )
    return run_audit(
        build_inputs(
            table.to_csv(index=False).encode(),
            DeclaredMetadata(return_frequency="monthly", return_unit="fraction", trials=100),
            benchmark_bytes=benchmark.to_csv(index=False).encode(),
        ),
        bootstrap_samples=20,
        risk_samples=20,
        challenge_samples=20,
    )


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_period_report_guard_and_complete_render(periodic_result, locale):
    page = render_html(periodic_result, watermark=False, locale=locale)
    assert find_claims(page) == []
    assert "id='return-series'" in page
    assert "periods_per_year=12" in page
    assert "DECLARED" in page and "MEASURED" in page
    assert "gross_pnl" not in page
    if locale in {"es", "pt"}:
        assert untranslated(periodic_result.model_dump(mode="json"), locale=locale) == []


def test_period_metadata_and_calendar_keep_first_loss(periodic_result):
    data = periodic_result.model_dump(mode="json")
    metadata = data["inputs"]["return_series"]
    assert metadata["basis"]["value"] == "net"
    assert metadata["basis"]["evidence"] == "DECLARED"
    assert metadata["unit"]["evidence"] == "DECLARED"
    assert metadata["benchmark_source"]["evidence"] == "DECLARED"
    assert metadata["gross"]["total_return"]["evidence"] == "MEASURED"
    assert metadata["gross"]["unit"]["value"] == "fraction"
    assert metadata["gross"]["unit"]["evidence"] == "DECLARED"
    assert metadata["net"]["total_return"] == data["performance"]["total_return"]
    assert data["benchmark"]["status"] == "MEASURED"
    assert data["benchmark"]["strategy_total_return"] == data["performance"]["total_return"]
    assert data["series"]["timestamps"][0].startswith("2020-01-31")
    assert data["series"]["opening_equity"] == 1
    assert data["series"]["period_months"][0]["value"]["value"] == pytest.approx(-0.08)
    json.dumps(data, allow_nan=False)


def test_ambiguous_period_path_is_not_measured(periodic_result):
    for name in ("ride", "stress", "cash_rate", "vix_regime", "challenge"):
        section = getattr(periodic_result, name)
        assert section["status"] == "NOT_MEASURED"
        assert "within-period path" in section["reason"]
