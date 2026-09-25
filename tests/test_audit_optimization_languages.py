"""MT5 optimisation exports from a terminal in another language.

MetaTrader 5 names the optimisation columns in the terminal's language
(Paso, Проход, Passagem...). The audit reads them under the English names
the plateau and forward checks use.
"""

from __future__ import annotations

import pytest

from quant_trade.audit.importers import ReportFormatError, parse_optimization
from quant_trade.audit.plateau import parameter_stability


def _cell(value: object) -> str:
    kind = "Number" if isinstance(value, int | float) else "String"
    return f'<Cell><Data ss:Type="{kind}">{value}</Data></Cell>'


def _export(header: list[str], rows: list[list[object]]) -> bytes:
    body = "".join("<Row>" + "".join(_cell(c) for c in row) + "</Row>" for row in [header, *rows])
    return (
        '<?xml version="1.0"?>\n<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" '
        'xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">'
        f'<Worksheet ss:Name="Tester"><Table>{body}</Table></Worksheet></Workbook>'
    ).encode()


def _grid(profit_at: int) -> list[tuple[int, int, float]]:
    return [
        (fast, slow, 800.0 - 10 * abs(fast - 12) - 3 * abs(slow - 48) + profit_at)
        for fast in (4, 8, 12, 16, 20)
        for slow in (24, 36, 48, 60, 72)
    ]


# As a Spanish terminal writes it: the metrics come after the trade count.
SPANISH = [
    "Paso",
    "Símbolo",
    "Resultado",
    "Beneficio",
    "Total de operaciones",
    "Factor de rentabilidad",
    "Beneficio esperado",
    "Reducción %",
    "Factor de recuperación",
    "Ratio de Sharpe",
    "FastMA",
    "SlowMA",
]
RUSSIAN = ["Проход", "Результат", "Прибыль", "Всего трейдов", "Прибыльность", "FastMA", "SlowMA"]


def test_a_spanish_export_is_read_under_english_names() -> None:
    rows = [
        [n, "EURUSD", 1.1, profit, 40, 1.1, 2.0, 5.0, 1.5, 0.8, fast, slow]
        for n, (fast, slow, profit) in enumerate(_grid(0))
    ]
    summary = parse_optimization(_export(SPANISH, rows))
    assert summary.passes == 25
    assert summary.parameters == ["FastMA", "SlowMA"]
    assert summary.table[0]["Profit"] == rows[0][3]
    review, _ = parameter_stability(
        summary.table, summary.parameters, report_inputs="FastMA=12; SlowMA=48"
    )
    assert review["chosen_by"] == "report"
    assert review["neighbours_found"]["value"] == 4


def test_a_russian_export_is_read_under_english_names() -> None:
    rows = [
        [n, 1.0, profit, 30, 1.2, fast, slow] for n, (fast, slow, profit) in enumerate(_grid(0))
    ]
    summary = parse_optimization(_export(RUSSIAN, rows))
    assert summary.parameters == ["FastMA", "SlowMA"]
    assert {"Pass", "Result", "Profit", "Trades", "Profit Factor"} <= set(summary.table[0])


@pytest.mark.parametrize(
    ("forward", "back", "named"),
    [
        ("Форвард результат", "Бэк результат", True),
        ("Resultado forward", "Resultado back", True),
        ("Resultado hacia adelante", "Resultado hacia atrás", True),
        ("Vorwärts Ergebnis", "Rückwärts Ergebnis", True),
        ("Columna uno", "Columna dos", False),
    ],
)
def test_a_translated_forward_pair_is_named_only_when_its_words_say_so(
    forward: str, back: str, named: bool
) -> None:
    header = ["Проход", forward, back, "Прибыль", "Всего трейдов", "FastMA"]
    rows = [[n, 1.0 + n, 2.0 + n, 10.0 * n, 20, 5 + n] for n in range(5)]
    table = parse_optimization(_export(header, rows)).table
    assert ("Forward Result" in table[0] and "Back Result" in table[0]) is named
    if named:
        assert table[1]["Forward Result"] == 2.0 and table[1]["Back Result"] == 3.0


def test_an_input_named_like_a_column_word_stays_an_input() -> None:
    header = ["Pass", "Result", "Profit", "Trades", "BackPeriod", "ForwardBars"]
    rows = [[n, 1.0, 5.0, 10, 3, 7] for n in range(3)]
    summary = parse_optimization(_export(header, rows))
    assert summary.parameters == ["BackPeriod", "ForwardBars"]


def test_an_unknown_language_still_says_which_header_is_missing() -> None:
    with pytest.raises(ReportFormatError) as error:
        parse_optimization(_export(["Numéro", "Valeur"], [[1, 2.0]]))
    assert error.value.code == "optimization_header"


@pytest.mark.parametrize(
    "header",
    [
        ["Pass", "Result", "Profit", "Custom", "Equity DD %", "Trades", "Drawdown", "Symbol"],
        ["Pass", "Result", "Profit", "Custom", "Equity DD %", "Trades", "Custom", "Lots"],
        [
            "Paso",
            "Resultado",
            "Beneficio",
            "Total de operaciones",
            "Reducción %",
            "Symbol",
            "Drawdown",
            "Custom",
        ],
    ],
)
def test_inputs_named_like_a_metric_stay_inputs(header: list[str]) -> None:
    rows = [[n, 1.0, 5.0 + n, 7.0, 3.0, 10, 2 + n, 4 + n] for n in range(3)]
    summary = parse_optimization(_export(header, rows))
    inputs = header[-2:] if header[0] == "Pass" else header[-3:]
    assert summary.parameters == inputs
    assert summary.table[1][inputs[-1]] == rows[1][-1]
    assert summary.table[1]["Profit"] == 6.0


def test_a_translated_metric_after_trades_is_not_an_input() -> None:
    header = ["Paso", "Resultado", "Beneficio", "Total de operaciones", "Reducción %", "FastMA"]
    summary = parse_optimization(_export(header, [[n, 1.0, 5.0, 10, 3.0, n] for n in range(3)]))
    assert summary.parameters == ["FastMA"]
    assert summary.table[0]["Equity DD %"] == 3.0


def test_an_unknown_language_says_how_to_export_it() -> None:
    turkish = ["Geçiş", "Sonuç", "Kâr", "Toplam işlem", "FastMA"]
    with pytest.raises(ReportFormatError) as error:
        parse_optimization(_export(turkish, [[1, 1.0, 5.0, 10, 3]]))
    assert "View > Languages" in str(error.value)
    assert "Ver > Idiomas" in error.value.message_es
