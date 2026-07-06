"""Append-only trial ledger.

Every backtest evaluation — each research run, every grid-search combination,
every walk-forward window fit — appends one line here. The ledger's entry
count and cross-trial Sharpe variance feed the deflated Sharpe ratio: without
an honest record of how many things were tried, the multiple-testing
correction cannot exist.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quant_trade.metrics.statistics import sharpe_variance_across_trials

LEDGER_FILENAME = "trial_ledger.jsonl"


def ledger_path(outputs_dir: str | Path) -> Path:
    return Path(outputs_dir) / LEDGER_FILENAME


def append_trial(outputs_dir: str | Path, entry: dict[str, Any]) -> Path:
    path = ledger_path(outputs_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"recorded_at_utc": datetime.now(UTC).isoformat(), **entry}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
    return path


def read_trials(outputs_dir: str | Path) -> list[dict[str, Any]]:
    path = ledger_path(outputs_dir)
    if not path.exists():
        return []
    trials = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            trials.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return trials


def ledger_stats(outputs_dir: str | Path) -> tuple[int, float]:
    """(trial count, cross-trial variance of per-period test Sharpes).

    Counts every recorded evaluation, not just the winners — using only
    surviving runs would understate the search and inflate the deflated
    Sharpe.
    """
    trials = read_trials(outputs_dir)
    sharpes = [
        float(t["test_sharpe_per_period"])
        for t in trials
        if t.get("test_sharpe_per_period") is not None
    ]
    return len(trials), sharpe_variance_across_trials(sharpes)
