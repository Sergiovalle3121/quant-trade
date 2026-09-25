"""Lone peak or plateau, from a synthetic MT5 optimisation export. Offline."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from quant_trade.audit.engine import run_audit
from quant_trade.audit.guard import assert_report_clean
from quant_trade.audit.i18n import untranslated
from quant_trade.audit.importers import parse_optimization
from quant_trade.audit.plateau import parameter_stability
from quant_trade.audit.report import render
from quant_trade.audit.schema import DeclaredMetadata, build_inputs

FIXTURES = Path(__file__).parent / "fixtures" / "audit_imports"
FAST = [4, 8, 12, 16, 20]
SLOW = [24, 36, 48, 60, 72]
HEADER = [
    "Pass",
    "Result",
    "Profit",
    "Expected Payoff",
    "Profit Factor",
    "Recovery Factor",
    "Sharpe Ratio",
    "Custom",
    "Equity DD %",
    "Trades",
    "FastMA",
    "SlowMA",
]


def _cell(value: object) -> str:
    kind = "Number" if isinstance(value, int | float) else "String"
    return f'<Cell><Data ss:Type="{kind}">{value}</Data></Cell>'


def _export(profit: Callable[[int, int], float]) -> bytes:
    rows = ["<Row>" + "".join(_cell(name) for name in HEADER) + "</Row>"]
    number = 0
    for fast in FAST:
        for slow in SLOW:
            value = profit(fast, slow)
            cells = [number, 10_000 + value, value, 1.0, 1.2, 0.5, 0.3, 0, 5.0, 40, fast, slow]
            rows.append("<Row>" + "".join(_cell(c) for c in cells) + "</Row>")
            number += 1
    return (
        '<?xml version="1.0"?>\n<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" '
        'xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">'
        '<Worksheet ss:Name="Tester Optimizator Results"><Table>'
        + "".join(rows)
        + "</Table></Worksheet></Workbook>"
    ).encode("utf-8")


def _peak(fast: int, slow: int) -> float:
    return 900.0 if (fast, slow) == (12, 48) else -150.0 + fast


def _plateau(fast: int, slow: int) -> float:
    return 800.0 - 10 * abs(fast - 12) - 3 * abs(slow - 48)


def _review(profit: Callable[[int, int], float], inputs: str | None = "FastMA=12; SlowMA=48"):  # type: ignore[no-untyped-def]
    summary = parse_optimization(_export(profit))
    return parameter_stability(summary.table, summary.parameters, report_inputs=inputs)


def test_export_rows_are_read() -> None:
    summary = parse_optimization(_export(_plateau))
    assert summary.passes == 25 and summary.parameters == ["FastMA", "SlowMA"]
    assert summary.table[0]["FastMA"] == 4 and summary.table[0]["Profit"] == pytest.approx(
        _plateau(4, 24)
    )


def test_lone_peak_is_flagged() -> None:
    review, flags = _review(_peak)
    assert review["chosen_by"] == "report"
    assert review["chosen"] == {"FastMA": 12, "SlowMA": 48}
    assert review["neighbours_found"]["value"] == 4
    assert review["neighbours_profitable"]["value"] == 0
    assert [(flag.code, flag.severity) for flag in flags] == [("ISOLATED_OPTIMUM", "WARN")]
    assert review["chosen_top_share"]["value"] == pytest.approx(1 / 25)


def test_plateau_is_clean() -> None:
    review, flags = _review(_plateau)
    assert flags == [] and review["clean"] is True
    assert review["neighbours_keep"]["value"] > 0.9


def test_without_matching_inputs_the_best_pass_is_used() -> None:
    review, _ = _review(_peak, inputs=None)
    assert review["chosen_by"] == "best" and review["chosen"] == {"FastMA": 12, "SlowMA": 48}


def test_sparse_optimisation_is_not_judged() -> None:
    summary = parse_optimization(_export(_peak))
    neighbours = {(8, 48), (16, 48), (12, 36), (12, 60)}
    sparse = [row for row in summary.table if (row["FastMA"], row["SlowMA"]) not in neighbours]
    review, flags = parameter_stability(
        sparse, summary.parameters, report_inputs="FastMA=12; SlowMA=48"
    )
    assert review["neighbours_profitable"]["evidence"] == "NOT_MEASURED" and flags == []


def test_no_export_is_not_measured() -> None:
    review, flags = parameter_stability([], [], report_inputs=None)
    assert review["status"] == "NOT_MEASURED" and flags == []


@pytest.mark.parametrize("locale", ["es", "en"])
def test_section_renders_clean_with_the_tester_report(locale: str) -> None:
    inputs = build_inputs(
        None,
        DeclaredMetadata(locale=locale),
        report_bytes=(FIXTURES / "mt5_tester.html").read_bytes(),
        report_filename="ReportTester.html",
        optimization_bytes=_export(_peak),
    )
    assert inputs.report_metadata["input_values"] == "FastMA=12; SlowMA=48"
    result = run_audit(inputs, bootstrap_samples=200)
    assert result.plateau is not None and result.plateau["chosen_by"] == "report"
    assert "ISOLATED_OPTIMUM" in {flag["code"] for flag in result.red_flags}
    html, _ = render(result, watermark=False)
    assert_report_clean(html)
    assert ("¿Pico aislado o meseta?" if locale == "es" else "Lone peak or plateau?") in html
    assert untranslated(result.model_dump(mode="json")) == []
