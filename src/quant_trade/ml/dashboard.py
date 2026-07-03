"""Static dashboard for ML research artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from quant_trade.ml.reports import WARNING


def write_dashboard(output_dir: Path) -> Path:
    metrics_path = output_dir / "metrics_test.json"
    metrics = (
        json.loads(metrics_path.read_text(encoding="utf-8"))
        if metrics_path.exists()
        else {}
    )
    dash = output_dir / "dashboard"
    dash.mkdir(parents=True, exist_ok=True)
    path = dash / "index.html"
    html = (
        "<html><body><h1>ML Alpha Lab</h1>"
        f"<p>{WARNING}</p><pre>{json.dumps(metrics, indent=2)}</pre>"
        "</body></html>"
    )
    path.write_text(html, encoding="utf-8")
    return path
