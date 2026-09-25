"""The report shows whether it read the file the way the platform did."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from audit_fixtures import csv_bytes, positive_drift, trades_frame

from quant_trade.audit.engine import run_audit
from quant_trade.audit.guard import find_claims
from quant_trade.audit.report import LABELS, _lead_number, _reading_html, _reading_rows
from quant_trade.audit.schema import DeclaredMetadata, build_inputs

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _data(meta: dict[str, str]) -> dict[str, Any]:
    inputs = build_inputs(
        csv_bytes(positive_drift(300)),
        DeclaredMetadata(),
        trades_bytes=csv_bytes(trades_frame(30)),
    )
    data = run_audit(inputs, now=NOW, audit_id="r1", bootstrap_samples=50).model_dump(mode="json")
    data["inputs"]["report_metadata"] = meta
    return data


def test_platform_figures_are_parsed_as_the_platform_prints_them() -> None:
    assert _lead_number("1 279.20 (38.80%)") == 1279.20
    assert _lead_number("-947.20") == -947.20
    assert _lead_number("59") == 59
    assert _lead_number("n/a") is None
    assert _lead_number(None) is None


def test_matching_totals_say_so_in_both_languages() -> None:
    data = _data({})
    stats = data["trade_stats"]
    data["inputs"]["report_metadata"] = {
        "declared_total_trades": str(stats["trade_count"]["value"]),
        "declared_total_net_profit": f"{stats['net_pnl']['value']:.2f}",
    }
    rows = _reading_rows(data)
    assert [row[3] for row in rows] == [True, True]
    for locale in ("es", "en"):
        html = _reading_html(data, LABELS[locale])
        assert LABELS[locale]["reading_all_ok"] in html
        assert find_claims(html) == []


def test_a_mismatch_is_shown_and_points_to_the_report_id() -> None:
    data = _data({"declared_total_trades": "999", "declared_total_net_profit": "1.00"})
    assert [row[3] for row in _reading_rows(data)] == [False, False]
    html = _reading_html(data, LABELS["es"])
    assert "No coincide" in html and LABELS["es"]["reading_some_bad"] in html


def test_no_platform_summary_means_no_section() -> None:
    assert _reading_html(_data({}), LABELS["es"]) == ""
