"""Which prop firm's challenge a daily history fits best.

A trader who is about to pay for a challenge wants to know, before paying,
under which firm's rules their own history would most often have passed,
and whether a pass would have kept inside the firm's best-day
(consistency) rule, which is behind many refused payouts. This module runs
the challenge simulator (``analytics.simulate_challenge``) once per
published preset, on the same resampled paths (same seed), and ranks them.

Only presets with a published source are compared, never the generic
reference. Every figure is MEASURED from the uploaded daily returns under
the simulator's stated assumptions; the rules are each firm's page on its
``as_of`` date. No class change, no recommendation to buy a challenge.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

from quant_trade.audit.analytics import simulate_challenge
from quant_trade.audit.prop_presets import PRESETS
from quant_trade.audit.schema import measured

#: Samples per preset; the ranking needs less precision than the chosen firm.
SAMPLES = 2000
#: When every program is at or above this, or at or below the low mark, the
#: ranking says nothing and the report says so in one sentence.
UNIFORM_HIGH = 0.99
UNIFORM_LOW = 0.01
#: Presets that stand for several identical phases in a row.
REPEATS = {"the5ers-bootcamp-step": 3}

NOTE = (
    "every published preset simulated on the same resampled daily paths, rules as each "
    "firm's page stated them on its as_of date; a program's phases are taken as fresh "
    "starts, so the chance of passing them all is the product of each phase's"
)

_FAILS = ("fail_daily_loss", "fail_total_loss", "unfinished")


def _main_risk(probability: dict[str, Any]) -> str:
    """The failure that ends most paths, or "none" when no path fails."""
    worst = max(_FAILS, key=lambda k: float(probability[k]["value"]))
    return worst if float(probability[worst]["value"]) > 0 else "none"


def _payable(row: dict[str, Any]) -> float:
    """The figure that matters for getting paid: within the best-day rule when
    the firm has one."""
    return float((row.get("pass_within_best_day") or row["pass"])["value"])


def _program(results: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    """One program: its phases' pass chances multiplied, the weakest phase's risk."""
    rules = results[0][1]["rules"]
    passing = clean = 1.0
    with_rule = False
    weakest: dict[str, Any] | None = None
    for key, result in results:
        probability = result["probability"]
        repeats = REPEATS.get(key, 1)
        phase_pass = float(probability["pass"]["value"])
        passing *= phase_pass**repeats
        best_day = result.get("best_day")
        if best_day:
            with_rule = True
            clean *= float(best_day["pass_within"]["value"]) ** repeats
        else:
            clean *= phase_pass**repeats
        if weakest is None or phase_pass < float(weakest["pass"]["value"]):
            weakest = probability
    assert weakest is not None
    row: dict[str, Any] = {
        "keys": [key for key, _ in results],
        "firm": rules["firm"],
        "program": rules["program"],
        "phases": sum(REPEATS.get(key, 1) for key, _ in results),
        "source_url": rules["source_url"],
        "as_of": rules["as_of"],
        "pass": measured(passing, NOTE),
        "main_risk": _main_risk(weakest),
    }
    if with_rule:
        row["pass_within_best_day"] = measured(clean, NOTE)
    return row


def firm_fit(
    daily_returns: pd.Series | np.ndarray | Sequence[float],
    *,
    samples: int = SAMPLES,
    seed: int = 0,
    known: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Every published program on the same paths, best pass odds first.

    ``known`` maps a preset key to a result already simulated on the same
    history and seed (the report's chosen firm), so that firm's row shows the
    same figure as its own section."""
    programs: dict[tuple[str, str], list[tuple[str, dict[str, Any]]]] = {}
    for key, rules in PRESETS.items():
        if not rules.source_url.startswith("https://"):
            continue
        result = (known or {}).get(key) or simulate_challenge(
            daily_returns, rules, samples=samples, seed=seed
        )
        if not result.get("method"):
            reason = result["probability"]["pass"].get("note", "not measured")
            return {"status": "NOT_MEASURED", "reason": reason}
        programs.setdefault((rules.firm, rules.program), []).append((key, result))
    rows = [_program(results) for results in programs.values()]
    rows.sort(key=lambda row: (-_payable(row), row["firm"], row["program"]))
    out: dict[str, Any] = {
        "status": "MEASURED",
        "note": NOTE,
        "samples": samples,
        "seed": seed,
        "firms": rows,
    }
    figures = [_payable(row) for row in rows]
    if min(figures) >= UNIFORM_HIGH:
        out["uniform"] = "all_pass"
    elif max(figures) <= UNIFORM_LOW:
        out["uniform"] = "all_fail"
        risks = [row["main_risk"] for row in rows if row["main_risk"] != "none"]
        out["common_risk"] = max(sorted(set(risks)), key=risks.count) if risks else "none"
    return out


__all__ = ["REPEATS", "SAMPLES", "firm_fit"]
