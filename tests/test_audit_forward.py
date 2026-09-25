"""Back against forward results, from a synthetic MT5 forward export. Offline."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from quant_trade.audit.engine import run_audit
from quant_trade.audit.forward import UNNAMED_FORWARD, forward_review, is_forward, unnamed_forward
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
    "Forward Result",
    "Back Result",
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


def _back(fast: int, slow: int) -> float:
    return 1000.0 - 20 * abs(fast - 12) - 5 * abs(slow - 48)


def _export(forward: Callable[[int, int], float], header: list[str] = HEADER) -> bytes:
    rows = ["<Row>" + "".join(_cell(name) for name in header) + "</Row>"]
    number = 0
    for fast in FAST:
        for slow in SLOW:
            profit = forward(fast, slow)
            cells = [
                number,
                10_000 + profit,
                10_000 + _back(fast, slow),
                profit,
                1.0,
                1.2,
                0.5,
                0.3,
                0,
                5.0,
                40,
                fast,
                slow,
            ]
            rows.append("<Row>" + "".join(_cell(c) for c in cells) + "</Row>")
            number += 1
    return (
        '<?xml version="1.0"?>\n<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" '
        'xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">'
        '<Worksheet ss:Name="Tester Optimizator Results"><Table>'
        + "".join(rows)
        + "</Table></Worksheet></Workbook>"
    ).encode("utf-8")


def _held(fast: int, slow: int) -> float:
    return _back(fast, slow) / 4 - 150.0


def _lost(fast: int, slow: int) -> float:
    # The backtest's best settings are the forward period's worst.
    return 150.0 - _back(fast, slow) / 4


def _review(forward: Callable[[int, int], float]):  # type: ignore[no-untyped-def]
    summary = parse_optimization(_export(forward))
    return forward_review(summary.table, summary.parameters, report_inputs="FastMA=12; SlowMA=48")


def test_forward_export_is_read_and_recognised() -> None:
    summary = parse_optimization(_export(_held))
    assert summary.parameters == ["FastMA", "SlowMA"]
    assert is_forward(summary.table)


def test_a_ranking_that_holds_is_clean() -> None:
    review, flags = _review(_held)
    assert flags == [] and review["clean"] is True
    assert review["rank_correlation"]["value"] == pytest.approx(1.0)
    assert review["top_in_profit"]["value"] == 1.0
    assert review["chosen"] == {"FastMA": 12, "SlowMA": 48}
    assert review["chosen_forward_share"]["value"] == 1.0


def test_a_ranking_that_flips_is_flagged() -> None:
    review, flags = _review(_lost)
    assert [(flag.code, flag.severity) for flag in flags] == [("FORWARD_NOT_HELD", "WARN")]
    assert review["rank_correlation"]["value"] < 0
    assert review["top_in_profit"]["value"] <= review["all_in_profit"]["value"]
    assert "best passes of the backtest" in flags[0].detail


def test_a_plain_export_or_too_few_passes_is_not_measured() -> None:
    plain = [{"Pass": 1.0, "Profit": 10.0}] * 30
    assert forward_review(plain, [], report_inputs=None)[0]["status"] == "NOT_MEASURED"
    summary = parse_optimization(_export(_held))
    review, flags = forward_review(summary.table[:10], summary.parameters, report_inputs=None)
    assert review["status"] == "NOT_MEASURED" and flags == []


def test_plateau_leaves_a_forward_export_alone() -> None:
    summary = parse_optimization(_export(_lost))
    review, flags = parameter_stability(summary.table, summary.parameters, report_inputs=None)
    assert review["status"] == "NOT_MEASURED" and flags == []
    assert "forward export" in review["reason"]


def test_forward_columns_with_other_names_are_not_read_as_a_plain_export() -> None:
    header = ["Pass", "Resultado forward", "Resultado back", *HEADER[3:]]
    summary = parse_optimization(_export(_lost, header))
    assert not is_forward(summary.table) and unnamed_forward(summary.table)
    for check in (forward_review, parameter_stability):
        review, flags = check(summary.table, summary.parameters, report_inputs="FastMA=12")
        assert review["status"] == "NOT_MEASURED" and flags == []
        assert review["reason"] == UNNAMED_FORWARD


def test_a_plain_export_is_not_taken_for_an_unnamed_forward_one() -> None:
    header = ["Pass", "Result", *HEADER[3:]]
    summary = parse_optimization(_export(_held, header))
    assert not unnamed_forward(summary.table)


@pytest.mark.parametrize("locale", ["es", "en"])
def test_section_renders_clean_with_the_tester_report(locale: str) -> None:
    inputs = build_inputs(
        None,
        DeclaredMetadata(locale=locale),
        report_bytes=(FIXTURES / "mt5_tester.html").read_bytes(),
        report_filename="ReportTester.html",
        optimization_bytes=_export(_lost),
    )
    result = run_audit(inputs, bootstrap_samples=200)
    assert result.forward is not None and result.forward["status"] == "MEASURED"
    assert "FORWARD_NOT_HELD" in {flag["code"] for flag in result.red_flags}
    html, _ = render(result, watermark=False)
    assert_report_clean(html)
    title = "¿Aguanta en el periodo forward?" if locale == "es" else "Does it hold in the forward"
    assert title in html
    assert untranslated(result.model_dump(mode="json")) == []
