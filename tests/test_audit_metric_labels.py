"""Every metric row in the technical tables carries a human label, never the
raw JSON key (``tracking_error``) a paying reader cannot decode."""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest
from audit_fixtures import (
    benchmark_lower_drift,
    csv_bytes,
    positive_drift,
    trades_following,
)

from quant_trade.audit.engine import run_audit
from quant_trade.audit.report import render_html
from quant_trade.audit.schema import DeclaredMetadata, build_inputs

RAW_KEY = re.compile(r"<tr><td>([a-z0-9]+(?:_[a-z0-9]+)+)</td>")


@pytest.fixture(scope="module")
def full_result():
    n = 1500
    inputs = build_inputs(
        csv_bytes(positive_drift(n)),
        DeclaredMetadata(trials=3, cost_bps_per_side=5, oos_start="2023-01-01"),
        trades_bytes=csv_bytes(trades_following(positive_drift(n))),
        benchmark_bytes=csv_bytes(benchmark_lower_drift(n)),
    )
    return run_audit(
        inputs, now=datetime(2026, 1, 1, tzinfo=UTC), audit_id="fixed", bootstrap_samples=300
    )


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_no_metric_row_shows_a_raw_key(full_result, locale: str) -> None:
    page = render_html(full_result, watermark=False, locale=locale)
    assert sorted(set(RAW_KEY.findall(page))) == []


@pytest.mark.parametrize(
    ("locale", "label"),
    [
        ("es", "Error de seguimiento"),
        ("en", "Tracking error"),
        ("pt", "Erro de rastreamento"),
    ],
)
def test_the_benchmark_table_names_the_tracking_error(full_result, locale, label) -> None:
    page = render_html(full_result, watermark=False, locale=locale)
    assert f"<tr><td>{label}</td>" in page
