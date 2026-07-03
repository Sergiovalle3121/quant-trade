from __future__ import annotations

import csv
import json
from pathlib import Path

from .models import utc_now
from .registry import list_trials


def generate_trial_dashboard(registry: dict, run_id: str | None = None) -> Path:
    run_id = run_id or utc_now().replace(":", "").split(".")[0]
    out = Path("outputs/trials/dashboard") / run_id
    out.mkdir(parents=True, exist_ok=True)
    trials = list_trials(registry)
    data = [t.to_dict() for t in trials]
    (out / "dashboard.json").write_text(
        json.dumps({"trials": data, "real_money_ready": False}, indent=2), encoding="utf-8"
    )
    for name, rows in [
        ("trials.csv", trials),
        ("active_trials.csv", [t for t in trials if t.status == "active"]),
        ("completed_trials.csv", [t for t in trials if t.status == "completed"]),
    ]:
        with (out / name).open("w", newline="", encoding="utf-8") as f:
            fields = [
                "trial_id",
                "status",
                "strategy_name",
                "benchmark",
                "start_date",
                "planned_end_date",
            ]
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            [w.writerow({k: t.to_dict().get(k) for k in fields}) for t in rows]
    for name in ["decisions.csv", "drift_summary.csv", "performance_summary.csv", "review_due.csv"]:
        (out / name).write_text("trial_id,status,real_money_ready\n", encoding="utf-8")
    (out / "index.html").write_text(
        (
            "<html><body><h1>Paper Trial Dashboard</h1>"
            "<p>SAFETY: paper-only, no real money, real_money_ready=false.</p></body></html>"
        ),
        encoding="utf-8",
    )
    return out
