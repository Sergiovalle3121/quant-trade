from __future__ import annotations

import csv
from dataclasses import asdict
from pathlib import Path

from quant_trade.campaigns.models import CampaignResult, RankedCandidate

_NON_METRIC_FIELDS = {"run_id", "strategy", "artifacts_complete", "rejection_reason"}


def write_run_index(path: Path, rows: list[dict[str, object]]) -> None:
    _write_csv(path, rows)


def write_results(path: Path, results: list[CampaignResult]) -> None:
    rows = []
    for result in results:
        rows.append(
            {
                "run_id": result.run_id,
                "strategy": result.strategy,
                **result.metrics,
                "artifacts_complete": result.artifacts_complete,
                "rejection_reason": result.rejection_reason,
            }
        )
    _write_csv(path, rows)


def write_ranking(path: Path, ranked: list[RankedCandidate]) -> None:
    _write_csv(path, [asdict(r) for r in ranked])


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({k for row in rows for k in row}) if rows else ["empty"]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def read_results(path: Path) -> list[CampaignResult]:
    results = []
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            metrics = {
                k: float(v) for k, v in row.items() if k not in _NON_METRIC_FIELDS and v != ""
            }
            results.append(
                CampaignResult(
                    row["run_id"],
                    row["strategy"],
                    metrics,
                    row.get("artifacts_complete", "True") == "True",
                    row.get("rejection_reason", ""),
                )
            )
    return results
