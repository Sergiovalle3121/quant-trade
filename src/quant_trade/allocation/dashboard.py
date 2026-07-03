from __future__ import annotations

from pathlib import Path

from .models import AllocationSimulationResult


def write_dashboard(out: Path, result: AllocationSimulationResult) -> Path:
    d = out / "dashboard"
    d.mkdir(parents=True, exist_ok=True)
    rows = "".join(
        f"<tr><td>{a.strategy_id}</td><td>{a.weight:.2%}</td><td>{a.capital:.2f}</td></tr>"
        for a in result.allocation.allocations
    )
    html = "".join(
        [
            "<!doctype html><html><body><h1>Paper Allocation Dashboard</h1>",
            "<p>Simulation only. real_money_ready=false. No live trading.</p>",
            "<table><tr><th>Strategy</th><th>Weight</th><th>Capital</th></tr>",
            rows,
            "</table><pre>",
            str(result.metrics),
            "</pre></body></html>",
        ]
    )
    p = d / "index.html"
    p.write_text(html, encoding="utf-8")
    return p
