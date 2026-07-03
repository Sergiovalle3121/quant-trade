from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .models import TrialConfig


def calculate_trial_day(start_date: date, current_date: date) -> int:
    return max(0, (current_date - start_date).days + 1)


def next_review_due(trial_config: TrialConfig, last_review_date: date | None) -> date:
    base = last_review_date or trial_config.start_date
    delta = {"daily": 1, "weekly": 7, "monthly": 30}[trial_config.review_frequency]
    return base + timedelta(days=delta)


def reviews_due(
    registry: dict[str, Any], as_of_date: date, include_completed: bool = False
) -> list[TrialConfig]:
    return [
        t
        for t in registry.get("trials", [])
        if (include_completed or t.status in {"active", "paused"})
        and next_review_due(t, None) <= as_of_date
    ]


def generate_review_calendar(trial_config: TrialConfig) -> Path:
    out = Path("outputs/trials") / trial_config.trial_id / "review_calendar.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    delta = {"daily": 1, "weekly": 7, "monthly": 30}[trial_config.review_frequency]
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["trial_id", "review_date", "review_type"])
        w.writeheader()
        d = trial_config.start_date
        while d <= trial_config.planned_end_date:
            w.writerow(
                {
                    "trial_id": trial_config.trial_id,
                    "review_date": d.isoformat(),
                    "review_type": trial_config.review_frequency,
                }
            )
            d += timedelta(days=delta)
    return out
