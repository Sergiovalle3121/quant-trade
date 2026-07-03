"""Static offline evidence dashboard."""

from __future__ import annotations

import html
import time
from pathlib import Path

from quant_trade.evidence.config import EvidenceConfig
from quant_trade.evidence.database import connect


def build_dashboard(config: EvidenceConfig, run_id: str | None = None) -> Path:
    run_id = run_id or f"dashboard_{int(time.time())}"
    out_dir = config.output_dir / "evidence" / run_id / "dashboard"
    out_dir.mkdir(parents=True, exist_ok=True)
    with connect(config.database_path) as conn:
        rows = list(
            conn.execute(
                "SELECT strategy_id, COUNT(*) AS count FROM artifacts "
                "GROUP BY strategy_id ORDER BY strategy_id"
            )
        )
    body = "".join(
        f"<tr><td>{html.escape(str(r['strategy_id']))}</td><td>{r['count']}</td></tr>" for r in rows
    )
    path = out_dir / "index.html"
    html_text = (
        "<html><body><h1>Evidence Dashboard</h1>"
        "<p>Paper-only research evidence. real_money_ready=false.</p>"
        "<table><tr><th>Strategy</th><th>Artifacts</th></tr>"
        f"{body}</table></body></html>"
    )
    path.write_text(html_text, encoding="utf-8")
    return path
