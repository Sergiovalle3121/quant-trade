"""Offline parity of the Pine arithmetic and its documented display examples.

This is not a Pine compiler: translate only the script's pure arithmetic
functions, then compare their actual expressions with the calculator.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from quant_trade.audit.calculator import CalculatorInput, compute
from quant_trade.audit.guard import find_claims

ROOT = Path(__file__).resolve().parents[1]
PINE = (ROOT / "tools/tradingview/rigor_luck_sharpe.pine").read_text(encoding="utf-8")
DOC = (ROOT / "docs/TRADINGVIEW_INDICATOR.md").read_text(encoding="utf-8")
CASES = [json.loads(line) for line in re.findall(r"^// PARITY: (.+)$", PINE, re.MULTILINE)]


@pytest.fixture(scope="module")
def pine_math() -> dict[str, Any]:
    """Execute the literal scalar formulas, not a second handwritten model.

    The bounded source block contains assignments, if/else and implicit
    returns only. Chart rendering and Pine's execution model remain untested.
    """
    block = PINE.split("// BEGIN CALCULATOR MATH\n", 1)[1].split("// END CALCULATOR MATH", 1)[0]
    lines: list[str] = []
    for raw in block.splitlines():
        if not raw.strip() or raw.lstrip().startswith("//"):
            continue
        line = re.sub(r"\b(?:float|int|bool) (?=[a-zA-Z_])", "", raw)
        if line.endswith(" =>"):
            line = "def " + line[:-3] + ":"
        elif line.lstrip().startswith(("if ", "else if ", "else")):
            line = line.replace("else if ", "elif ") + ":"
        elif not re.search(r"(?<![<>=!])(?::?=)(?!=)", line):
            line = "    return " + line.strip()
        line = line.replace(":=", "=")
        line = re.sub(r"\bna\b", "float('nan')", line)
        lines.append(line)
    namespace: dict[str, Any] = {
        "math": SimpleNamespace(
            sqrt=math.sqrt, log=math.log, exp=math.exp, floor=math.floor, min=min, max=max
        )
    }
    exec(compile("\n".join(lines), "<Pine arithmetic only>", "exec"), namespace)
    return namespace


@pytest.mark.parametrize("case", CASES)
def test_documented_pine_displays_match_calculator(
    pine_math: dict[str, Any], case: dict[str, Any]
) -> None:
    value = CalculatorInput(
        **{key: case[key] for key in ("sharpe", "years", "trials", "periods_per_year")}
    )
    calculated = compute(value)
    actual = pine_math["f_luck_numbers"](
        value.sharpe, value.years, value.trials, value.periods_per_year
    )
    for output, key, expected_display in zip(
        actual, ("luck_sharpe", "sharpe_after"), (case["luck"], case["after"]), strict=True
    ):
        assert output == pytest.approx(calculated[key]["value"], abs=0.00001)
        assert f"{output:.2f}" == expected_display
        assert f"{calculated[key]['value']:.2f}" == expected_display


@pytest.mark.parametrize("periods", [252, 52, 12])
@pytest.mark.parametrize(
    "sharpe,years,trials",
    [(0.05, 2.0, 2), (1.8, 3.0, 10000000), (10.0, 50.0, 100), (4.0, 5.0, 2)],
)
def test_pine_tail_and_input_extremes_match_calculator(
    pine_math: dict[str, Any], periods: int, sharpe: float, years: float, trials: int
) -> None:
    result = compute(CalculatorInput(sharpe, years, trials, periods))
    actual = pine_math["f_luck_numbers"](sharpe, years, trials, periods)
    assert actual == pytest.approx(
        [result["luck_sharpe"]["value"], result["sharpe_after"]["value"]], abs=0.00001
    )


@pytest.mark.parametrize("years,trials,periods", [(0.1, 100, 12), (0.1, 100, 52), (3, 1, 252)])
def test_pine_withholds_numbers_when_calculator_has_no_discount(
    pine_math: dict[str, Any], years: float, trials: int, periods: int
) -> None:
    result = compute(CalculatorInput(1.8, years, trials, periods))
    assert "luck_sharpe" not in result and "sharpe_after" not in result
    assert all(math.isnan(v) for v in pine_math["f_luck_numbers"](1.8, years, trials, periods))


@pytest.mark.parametrize("value", [19.5, 20.5, 21.5, 22.5, 125.49, 125.51])
def test_observation_rounding_matches_python(pine_math: dict[str, Any], value: float) -> None:
    assert pine_math["f_round_even"](value) == round(value)


def test_chart_frequency_mapping_and_unsupported_intervals(pine_math: dict[str, Any]) -> None:
    frequency = pine_math["f_periods"]
    assert frequency(True, False, False, 1) == 252
    assert frequency(False, True, False, 1) == 52
    assert frequency(False, False, True, 1) == 12
    assert frequency(False, False, False, 1) == 0
    assert frequency(True, False, False, 2) == 0
    assert frequency(False, True, False, 2) == 0
    assert frequency(False, False, True, 3) == 0
    assert all(math.isnan(v) for v in pine_math["f_luck_numbers"](1.8, 3, 100, 0))


def test_script_and_publication_copy_are_guard_clean_and_declared_only() -> None:
    assert len(CASES) == 3
    assert {case["periods_per_year"] for case in CASES} == {252, 52, 12}
    assert find_claims(PINE) == []
    assert find_claims(DOC) == []
    assert PINE.startswith("//@version=5\nindicator(")
    assert len(re.findall(r"\binput\.(?:float|int)\(", PINE)) == 3
    assert re.search(r"\b(?:strategy|request|alert|alertcondition)\s*[.(]", PINE) is None
    assert "Cifras declaradas · no es una auditoría · rigorscore.com/calculator?ref=tv" in PINE
    values = re.findall(r"^    table\.cell\(panel, 1, [1-6], (.+)$", PINE, re.MULTILINE)
    assert len(values) == 6
    assert all("DECLARED" in value for value in values)
