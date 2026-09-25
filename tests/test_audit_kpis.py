"""The executive summary shows measured key figures, and none of them before payment."""

from __future__ import annotations

from datetime import UTC, datetime

from audit_fixtures import csv_bytes, positive_drift, trades_frame

from quant_trade.audit.engine import run_audit
from quant_trade.audit.guard import find_claims
from quant_trade.audit.report import LABELS, _kpi_list, render_html
from quant_trade.audit.schema import DeclaredMetadata, build_inputs

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _result(trades: bool = True):
    inputs = build_inputs(
        csv_bytes(positive_drift(600)),
        DeclaredMetadata(trials=1, cost_bps_per_side=2),
        trades_bytes=csv_bytes(trades_frame(30)) if trades else None,
    )
    return run_audit(inputs, now=NOW, audit_id="kpi01", bootstrap_samples=200)


def test_paid_report_shows_the_key_figures() -> None:
    result = _result()
    data = result.model_dump(mode="json")
    kpis = dict((label, shown) for label, shown, _ in _kpi_list(data, LABELS["es"]))
    total = data["performance"]["total_return"]["value"]
    assert kpis["Retorno total"] == f"{total:+.1%}"
    stress = next(
        row for row in data["stress"]["trades"]["rows"] if row["scenario"] == "best_5_trades"
    )
    assert kpis["Sin las 5 mejores operaciones"] == f"{stress['result']['value']:+,.2f}"
    page = render_html(result, watermark=False, free_mode=False)
    assert "Resumen ejecutivo" in page
    assert f"{total:+.1%}" in page
    assert find_claims(page) == []


def test_locked_report_names_the_figures_without_values() -> None:
    result = _result()
    data = result.model_dump(mode="json")
    locked = render_html(result, watermark=True, free_mode=False, checkout_url="/c")
    assert "Resumen ejecutivo" in locked
    assert "class='kpi locked'" in locked
    for _, shown, _ in _kpi_list(data, LABELS["es"]):
        assert f"<b>{shown}</b>" not in locked
    # A locked tile shows a lock and a placeholder bar, never a stand-in figure.
    tile = locked.split("class='kpi locked'", 1)[1].split("</a>", 1)[0]
    assert "<svg" in tile and "<i></i>" in tile and "•" not in tile
    # Tapping a locked figure goes to the unlock box, which the page carries.
    assert "href='#unlock'" in tile and "id='unlock'" in locked


def test_figures_that_were_not_measured_are_left_out() -> None:
    data = _result(trades=False).model_dump(mode="json")
    labels = [label for label, _, _ in _kpi_list(data, LABELS["en"])]
    assert "Profit factor" not in labels
    assert "Without the best 5 trades" not in labels
    assert "Without the best 5 periods" in labels
    assert "Total return" in labels
