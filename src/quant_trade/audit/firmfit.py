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
#: Presets that stand for several identical phases in a row.
REPEATS = {"the5ers-bootcamp-step": 3}

NOTE = (
    "every published preset simulated on the same resampled daily paths, rules as each "
    "firm's page stated them on its as_of date; a program's phases are taken as fresh "
    "starts, so the chance of passing them all is the product of each phase's"
)

_FAILS = ("fail_daily_loss", "fail_total_loss", "unfinished")


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
        "main_risk": max(_FAILS, key=lambda k: float(weakest[k]["value"])),
    }
    if with_rule:
        row["pass_within_best_day"] = measured(clean, NOTE)
    return row


def firm_fit(
    daily_returns: pd.Series | np.ndarray | Sequence[float],
    *,
    samples: int = SAMPLES,
    seed: int = 0,
) -> dict[str, Any]:
    """Every published program on the same paths, best pass odds first."""
    programs: dict[tuple[str, str], list[tuple[str, dict[str, Any]]]] = {}
    for key, rules in PRESETS.items():
        if not rules.source_url.startswith("https://"):
            continue
        result = simulate_challenge(daily_returns, rules, samples=samples, seed=seed)
        if not result.get("method"):
            reason = result["probability"]["pass"].get("note", "not measured")
            return {"status": "NOT_MEASURED", "reason": reason}
        programs.setdefault((rules.firm, rules.program), []).append((key, result))
    rows = [_program(results) for results in programs.values()]
    rows.sort(key=lambda row: (-float(row["pass"]["value"]), row["firm"], row["program"]))
    return {"status": "MEASURED", "note": NOTE, "samples": samples, "seed": seed, "firms": rows}


__all__ = ["REPEATS", "SAMPLES", "firm_fit"]
