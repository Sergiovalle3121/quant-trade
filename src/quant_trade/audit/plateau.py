"""Isolated peak or plateau: the chosen settings against their neighbours.

A robot whose chosen settings sit on a lone peak of the optimisation (one
step away on any parameter and the result collapses) was most likely fitted
to the history's noise. Settings on a plateau keep most of the result when
a parameter moves by one step. Buyers and prop traders are told to look for
the plateau; the MetaTrader optimisation export holds every pass needed to
check it, and nobody reads it for them.

From the uploaded MT5 optimisation export:

* the chosen pass is the one whose parameters match the inputs printed in
  the uploaded tester report; without a match, the pass with the highest
  profit (what a seller usually picks), and the section says so;
* its neighbours are the passes one step away on a single parameter (the
  next lower or higher value tried), with every other parameter unchanged;
* the section reports how many neighbours stay profitable, the share of the
  chosen profit their median keeps, where the chosen pass ranks among all
  passes and how many passes were profitable at all.

``ISOLATED_OPTIMUM`` (WARN) is raised when at least two neighbours exist,
the chosen profit is positive, and either fewer than half the neighbours
are profitable or their median keeps less than half of the chosen profit.
Every figure is MEASURED from the export's own rows; the export's profits
are the optimiser's, not re-computed trades, and a genetic optimisation
may not have tried the neighbours.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from typing import Any

from quant_trade.audit.redflags import RedFlag
from quant_trade.audit.schema import measured, not_measured

MIN_PASSES = 10
MIN_NEIGHBOURS = 2
#: Neighbours' median must keep at least this share of the chosen profit ...
KEEP_SHARE = 0.5
#: ... and at least this share of neighbours must be profitable.
PROFITABLE_SHARE = 0.5
MAX_LISTED = 12

METRICS: tuple[str, ...] = ("Profit", "Result")
NOTE = "from the rows of the optimisation export"


def _metric(table: Sequence[dict[str, float]]) -> str | None:
    for name in METRICS:
        if table and all(name in row for row in table):
            return name
    return None


def _parse_inputs(raw: str | None) -> dict[str, float]:
    values: dict[str, float] = {}
    for part in (raw or "").split(";"):
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        try:
            values[name.strip()] = float(value.strip())
        except ValueError:
            continue
    return values


def _key(row: dict[str, float], names: Sequence[str]) -> tuple[float | None, ...]:
    return tuple(row.get(name) for name in names)


def parameter_stability(
    table: Sequence[dict[str, float]],
    parameters: Sequence[str],
    *,
    report_inputs: str | None,
) -> tuple[dict[str, Any], list[RedFlag]]:
    """Neighbours of the chosen pass in an MT5 optimisation export."""
    if not table:
        return {"status": "NOT_MEASURED", "reason": "no optimisation file uploaded"}, []
    metric = _metric(table)
    varied = [name for name in parameters if len({row.get(name) for row in table} - {None}) >= 2]
    if metric is None or not varied or len(table) < MIN_PASSES:
        return {
            "status": "NOT_MEASURED",
            "reason": f"needs at least {MIN_PASSES} passes with a profit column and a "
            "parameter that varies",
        }, []

    inputs = _parse_inputs(report_inputs)
    wanted = {name: inputs[name] for name in varied if name in inputs}
    chosen = None
    if len(wanted) == len(varied):
        chosen = next(
            (row for row in table if all(row.get(n) == v for n, v in wanted.items())), None
        )
    chosen_by = "report"
    if chosen is None:
        chosen = max(table, key=lambda row: row[metric])
        chosen_by = "best"
    chosen_value = chosen[metric]

    index = {_key(row, varied): row for row in table}
    neighbours: list[dict[str, Any]] = []
    for position, name in enumerate(varied):
        steps = sorted({row[name] for row in table if name in row})
        at = steps.index(chosen[name])
        for other in (at - 1, at + 1):
            if not 0 <= other < len(steps):
                continue
            probe = list(_key(chosen, varied))
            probe[position] = steps[other]
            row = index.get(tuple(probe))
            if row is not None:
                neighbours.append({"parameter": name, "value": steps[other], "result": row[metric]})

    results = [row[metric] for row in table]
    rank = sum(1 for value in results if value > chosen_value)
    review: dict[str, Any] = {
        "status": "MEASURED",
        "metric": metric,
        "chosen_by": chosen_by,
        "chosen": {name: chosen[name] for name in varied},
        "chosen_result": measured(chosen_value, NOTE),
        "passes": measured(len(table), NOTE),
        "passes_in_profit": measured(sum(value > 0 for value in results) / len(results), NOTE),
        "chosen_top_share": measured((rank + 1) / len(results), "rank of the chosen pass / passes"),
        "neighbours_found": measured(len(neighbours), NOTE),
        "neighbour_list": neighbours[:MAX_LISTED],
    }
    if len(neighbours) < MIN_NEIGHBOURS:
        reason = "the optimisation did not try the settings one step away (genetic or sparse)"
        review["neighbours_in_profit"] = not_measured(reason)
        review["neighbours_keep"] = not_measured(reason)
        review["clean"] = True
        return review, []

    values = [item["result"] for item in neighbours]
    profitable = sum(value > 0 for value in values) / len(values)
    keep = statistics.median(values) / chosen_value if chosen_value > 0 else None
    review["neighbours_in_profit"] = measured(profitable, NOTE)
    review["neighbours_keep"] = (
        measured(keep, "median neighbour profit / chosen profit")
        if keep is not None
        else not_measured("the chosen pass shows no profit")
    )
    flags: list[RedFlag] = []
    if chosen_value > 0 and (
        profitable < PROFITABLE_SHARE or (keep is not None and keep < KEEP_SHARE)
    ):
        flags.append(
            RedFlag(
                "ISOLATED_OPTIMUM",
                "WARN",
                f"{len(neighbours)} settings one step away keep {max(keep or 0.0, 0.0):.0%} of the "
                f"chosen profit at the median and {profitable:.0%} of them end with a profit: the "
                "chosen settings look like a lone peak",
                keep,
            )
        )
    review["clean"] = not flags
    return review, flags


__all__ = ["KEEP_SHARE", "MIN_PASSES", "PROFITABLE_SHARE", "parameter_stability"]
