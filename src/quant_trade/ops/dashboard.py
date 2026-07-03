from __future__ import annotations

import html
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .reports import redact, write_csv, write_json

SAFETY_BANNER = "Paper trading / dry-run only. No live trading."
DASHBOARD_SECTIONS = [
    "Session overview",
    "Latest run status",
    "Reliability metrics",
    "Risk metrics",
    "Drawdown summary",
    "Orders/fills summary",
    "Fill analysis",
    "Reconciliation status",
    "Active alerts",
    "Open incidents",
    "Kill switch status",
    "Data freshness",
    "Artifact integrity",
    "Readiness status",
    "Recommended actions",
]


def generate_dashboard(
    out: Path,
    sessions: Sequence[object],
    reliability: dict[str, Any],
    alerts: list[dict[str, Any]] | None = None,
    incidents: list[dict[str, Any]] | None = None,
) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    data = redact(
        {
            "safety": SAFETY_BANNER,
            "sessions": [getattr(session, "__dict__", session) for session in sessions],
            "reliability": reliability,
            "alerts": alerts or [],
            "incidents": incidents or [],
            "recommended_actions": [
                "Review warnings",
                "Resolve critical alerts",
                "Run safety drills",
            ],
        }
    )
    write_json(out / "dashboard.json", data)
    write_csv(out / "sessions.csv", data["sessions"])
    write_csv(out / "reliability.csv", [data["reliability"]])
    write_csv(out / "alerts.csv", data["alerts"])
    write_csv(out / "incidents.csv", data["incidents"])
    write_csv(out / "risk_summary.csv", [{"risk": "paper_only", "real_money_ready": False}])
    write_csv(out / "latest_runs.csv", [{"status": data["reliability"].get("status", "unknown")}])

    body = ["<h1>Paper Trading Operations Dashboard</h1>", f"<strong>{SAFETY_BANNER}</strong>"]
    for section in DASHBOARD_SECTIONS:
        body.append(f"<h2>{html.escape(section)}</h2><pre>{html.escape(str(data))}</pre>")
    index = out / "index.html"
    index.write_text(f"<!doctype html><html><body>{''.join(body)}</body></html>", encoding="utf-8")
    return index
