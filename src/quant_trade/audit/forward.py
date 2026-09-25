"""Does the optimisation hold in the forward period?

MetaTrader 5 can split an optimisation in two: the passes are run on a main
period, and the same settings are then run on a later "forward" period the
optimiser never ranked on. Its forward export lists, for every pass, the
criterion in both periods ("Back Result" and "Forward Result") and the
forward period's statistics (Profit, Trades ...). Buyers and developers are
told to run it and to distrust settings whose forward result collapses, but
the export is a long table nobody reads.

From that export:

* the rank correlation (Spearman) between the back and forward criterion:
  near zero or below, the backtest ranking says nothing about new data;
* how often the best passes of the backtest (the top tenth by Back Result,
  at least five) end the forward period with a profit, against all passes;
* where the chosen pass (matching the tester report's inputs) lands in the
  forward period.

``FORWARD_NOT_HELD`` (WARN) is raised when the rank correlation is zero or
below, or when the best backtest passes end the forward period with a profit
less often than half the time and no more often than the average pass.
Every figure is MEASURED from the export's rows. It measures one forward
window of the optimiser's own choosing; it says nothing about later periods.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from typing import Any

import pandas as pd

from quant_trade.audit.redflags import RedFlag
from quant_trade.audit.schema import measured, not_measured

BACK = "Back Result"
FORWARD = "Forward Result"
PROFIT = "Profit"
MIN_PASSES = 20
TOP_SHARE = 0.10
MIN_TOP = 5
#: The best passes must end the forward period with a profit at least this often.
TOP_IN_PROFIT = 0.5

NOTE = "from the rows of the forward optimisation export"
NOT_FORWARD = (
    "the optimisation file is not a forward export (no Forward Result and Back Result columns)"
)


UNNAMED_FORWARD = (
    "the optimisation file has two result columns before Profit, as a forward export does, "
    "but they are not named Forward Result and Back Result; export it again from a terminal "
    "set to English"
)


def is_forward(table: Sequence[dict[str, float]]) -> bool:
    """True when every row carries both the back and the forward criterion."""
    return bool(table) and all(BACK in row and FORWARD in row for row in table)


def unnamed_forward(table: Sequence[dict[str, float]]) -> bool:
    """A forward export whose result columns carry names the audit does not know.

    A plain export reads Pass, Result, Profit; a forward export Pass, Forward
    Result, Back Result, Profit. Two unknown columns between Pass and Profit
    (a terminal in another language, say) must not be read as a plain export:
    its Profit column would be the forward period's.
    """
    if not table or is_forward(table):
        return False
    names = list(table[0])
    return len(names) > 3 and names[0] == "Pass" and names[3] == PROFIT and "Result" not in names


def _parse_inputs(raw: str | None) -> dict[str, float]:
    values: dict[str, float] = {}
    for part in (raw or "").split(";"):
        name, sep, value = part.partition("=")
        if not sep:
            continue
        try:
            values[name.strip()] = float(value.strip())
        except ValueError:
            continue
    return values


def forward_review(
    table: Sequence[dict[str, float]],
    parameters: Sequence[str],
    *,
    report_inputs: str | None,
) -> tuple[dict[str, Any], list[RedFlag]]:
    """Back against forward results of an MT5 forward optimisation export."""
    if not table:
        return {"status": "NOT_MEASURED", "reason": "no optimisation file uploaded"}, []
    if unnamed_forward(table):
        return {"status": "NOT_MEASURED", "reason": UNNAMED_FORWARD}, []
    if not is_forward(table):
        return {"status": "NOT_MEASURED", "reason": NOT_FORWARD}, []
    rows = [row for row in table if math.isfinite(row[BACK]) and math.isfinite(row[FORWARD])]
    if len(rows) < MIN_PASSES:
        return {
            "status": "NOT_MEASURED",
            "reason": f"needs at least {MIN_PASSES} passes with a back and a forward result",
        }, []

    back = pd.Series([row[BACK] for row in rows], dtype=float)
    forward = pd.Series([row[FORWARD] for row in rows], dtype=float)
    if back.nunique() < 2 or forward.nunique() < 2:
        return {
            "status": "NOT_MEASURED",
            "reason": "every pass has the same back or forward result",
        }, []
    rho = float(back.rank().corr(forward.rank()))

    top_count = min(len(rows), max(MIN_TOP, math.ceil(TOP_SHARE * len(rows))))
    ranked = sorted(range(len(rows)), key=lambda i: (-rows[i][BACK], i))
    top = [rows[i] for i in ranked[:top_count]]
    has_profit = all(PROFIT in row and math.isfinite(row[PROFIT]) for row in rows)

    review: dict[str, Any] = {
        "status": "MEASURED",
        "passes": measured(len(rows), NOTE),
        "rank_correlation": measured(
            rho, "Spearman correlation between the back and the forward result of every pass"
        ),
        "top_count": measured(
            top_count, "the best tenth of the passes by back result, at least five"
        ),
    }
    top_in_profit = all_in_profit = None
    if has_profit:
        top_in_profit = sum(row[PROFIT] > 0 for row in top) / len(top)
        all_in_profit = sum(row[PROFIT] > 0 for row in rows) / len(rows)
        review["top_in_profit"] = measured(
            top_in_profit, "share of the best backtest passes with a forward profit"
        )
        review["all_in_profit"] = measured(
            all_in_profit, "share of all passes with a forward profit"
        )
        review["top_forward_median"] = measured(
            statistics.median(row[PROFIT] for row in top),
            "median forward profit of the best backtest passes",
        )
        review["all_forward_median"] = measured(
            statistics.median(row[PROFIT] for row in rows),
            "median forward profit of all passes",
        )
    else:
        reason = "the export has no Profit column for the forward period"
        for key in ("top_in_profit", "all_in_profit", "top_forward_median", "all_forward_median"):
            review[key] = not_measured(reason)

    varied = [name for name in parameters if len({row.get(name) for row in rows} - {None}) >= 2]
    inputs = _parse_inputs(report_inputs)
    chosen = None
    if varied and all(name in inputs for name in varied):
        chosen = next(
            (row for row in rows if all(row.get(name) == inputs[name] for name in varied)), None
        )
    if chosen is not None:
        below = sum(value < chosen[FORWARD] for value in forward)
        review["chosen"] = {name: chosen[name] for name in varied}
        review["chosen_forward_share"] = measured(
            below / (len(rows) - 1), "share of the other passes with a lower forward result"
        )
        review["chosen_forward_profit"] = (
            measured(chosen[PROFIT], "forward profit of the pass matching the tester report")
            if has_profit
            else not_measured("the export has no Profit column for the forward period")
        )
    else:
        review["chosen_forward_share"] = not_measured(
            "no pass matches the inputs of the uploaded tester report"
        )
        review["chosen_forward_profit"] = not_measured(
            "no pass matches the inputs of the uploaded tester report"
        )

    flags: list[RedFlag] = []
    ranking_fails = rho <= 0
    top_fails = (
        top_in_profit is not None
        and all_in_profit is not None
        and top_in_profit < TOP_IN_PROFIT
        and top_in_profit <= all_in_profit
    )
    if ranking_fails or top_fails:
        if top_in_profit is not None and all_in_profit is not None:
            detail = (
                f"the {top_count} best passes of the backtest end the forward period with a "
                f"profit in {top_in_profit:.0%} of cases, against {all_in_profit:.0%} for all "
                f"passes; rank correlation between the periods {rho:.2f}"
            )
        else:
            detail = f"rank correlation between the back and forward results {rho:.2f}"
        flags.append(RedFlag("FORWARD_NOT_HELD", "WARN", detail, rho))
    review["clean"] = not flags
    return review, flags


__all__ = [
    "BACK",
    "FORWARD",
    "MIN_PASSES",
    "UNNAMED_FORWARD",
    "forward_review",
    "is_forward",
    "unnamed_forward",
]
