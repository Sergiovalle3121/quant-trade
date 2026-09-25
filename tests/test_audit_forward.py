"""Back against forward results, from a synthetic MT5 forward export. Offline."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from quant_trade.audit.engine import run_audit
from quant_trade.audit.forward import UNNAMED_FORWARD, forward_review, is_forward, unnamed_forward
from quant_trade.audit.guard import assert_report_clean, find_claims
from quant_trade.audit.i18n import untranslated
from quant_trade.audit.importers import parse_optimization
from quant_trade.audit.plateau import parameter_stability
from quant_trade.audit.report import render
from quant_trade.audit.schema import DeclaredMetadata, build_inputs
from quant_trade.audit.settings import AuditSettings
from quant_trade.audit.store import make_store
from quant_trade.audit.web import create_app

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
    # Names that do not say which period each column is (a translation the
    # importer has no words for) stay unnamed.
    header = ["Pass", "Columna 1", "Columna 2", *HEADER[3:]]
    summary = parse_optimization(_export(_lost, header))
    assert not is_forward(summary.table) and unnamed_forward(summary.table)
    for check in (forward_review, parameter_stability):
        review, flags = check(summary.table, summary.parameters, report_inputs="FastMA=12")
        assert review["status"] == "NOT_MEASURED" and flags == []
        assert review["reason"] == UNNAMED_FORWARD


def test_a_translated_forward_export_is_reviewed() -> None:
    header = ["Проход", "Форвард результат", "Бэк результат", "Прибыль", *HEADER[4:]]
    summary = parse_optimization(_export(_lost, header))
    assert is_forward(summary.table)
    review, _ = forward_review(summary.table, summary.parameters, report_inputs="FastMA=12")
    assert review["status"] == "MEASURED"


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


@pytest.mark.parametrize("cell", ["", "-", "n/a"])
def test_a_pass_without_a_forward_result_keeps_the_export_a_forward_one(cell: str) -> None:
    # One blank forward cell used to make the whole file a plain export, so
    # the plateau check read the forward period's Profit as the backtest's.
    first = f'<Data ss:Type="Number">{10_000 + _lost(FAST[0], SLOW[0])}</Data>'
    export = _export(_lost).decode()
    assert first in export
    summary = parse_optimization(
        export.replace(first, f'<Data ss:Type="String">{cell}</Data>', 1).encode()
    )
    assert "Forward Result" not in summary.table[0]
    assert is_forward(summary.table)
    review, flags = forward_review(summary.table, summary.parameters, report_inputs="FastMA=12")
    assert review["status"] == "MEASURED" and review["passes"]["value"] == 24
    assert [flag.code for flag in flags] == ["FORWARD_NOT_HELD"]
    plateau, plateau_flags = parameter_stability(
        summary.table, summary.parameters, report_inputs=None
    )
    assert plateau["status"] == "NOT_MEASURED" and plateau_flags == []
    assert "forward export" in plateau["reason"]


def test_unnamed_forward_columns_are_found_past_a_blank_first_row() -> None:
    header = ["Pass", "Columna 1", "Columna 2", *HEADER[3:]]
    table = [dict(values) for values in parse_optimization(_export(_lost, header)).table]
    del table[0]["Columna 1"]
    assert unnamed_forward(table)


def test_the_optimisation_export_may_be_as_large_as_a_report(tmp_path: Path) -> None:
    # About 900 bytes a pass: a 5 MB cap refused common genetic runs.
    export = _export(_lost)
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        bootstrap_samples=100,
        max_upload_bytes=len(export) * 2 // 3,
    )
    client = TestClient(create_app(settings, make_store(settings.database_url)))
    files = {
        "report": ("ReportTester.html", (FIXTURES / "mt5_tester.html").read_bytes(), "text/html"),
        "optimization": ("ReportOptimizer.xml", export, "text/xml"),
    }
    response = client.post("/audits", files=files, data={"consent": "on"}, follow_redirects=False)
    assert response.status_code == 303


@pytest.mark.parametrize(("lang", "hint"), [("es", "genético"), ("en", "genetic")])
def test_an_optimisation_over_the_limit_says_what_to_do(
    tmp_path: Path, lang: str, hint: str
) -> None:
    export = _export(_lost)
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db", max_upload_bytes=len(export) // 3
    )
    client = TestClient(create_app(settings, make_store(settings.database_url)))
    files = {
        "report": ("ReportTester.html", (FIXTURES / "mt5_tester.html").read_bytes(), "text/html"),
        "optimization": ("ReportOptimizer.xml", export, "text/xml"),
    }
    response = client.post("/audits", files=files, data={"consent": "on", "locale": lang})
    assert response.status_code == 413
    assert hint in response.text
    assert find_claims(response.text) == []


def test_forward_section_answers_first_then_a_two_by_two_grid() -> None:
    from quant_trade.audit.report import LABELS, _forward_html

    for forward in (_review(_lost)[0], _review(_held)[0]):
        html = _forward_html(forward, LABELS["es"])
        assert html.index("live-verdict") < html.index("<div class='facts pairs'>")
        assert html.count("<div class='fact'>") + html.count("<div class='fact neg'>") == 4
