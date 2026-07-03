"""Static data lake dashboard."""

from __future__ import annotations

import html
from pathlib import Path


def render_dashboard(registry: dict[str, list[dict]], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for did, versions in sorted(registry.items()):
        latest = versions[-1]
        rows.append(
            "<tr>"
            f"<td>{html.escape(did)}</td>"
            f"<td>{html.escape(latest['version'])}</td>"
            f"<td>{html.escape(latest['provider'])}</td>"
            f"<td>{html.escape(latest['quality_status'])}</td>"
            f"<td>{latest['row_count']}</td>"
            "</tr>"
        )
    header = (
        "<html><body><h1>Data Lake Dashboard</h1>"
        "<p>Research/backtesting only. No live trading readiness implied.</p>"
        "<table><tr><th>Dataset</th><th>Version</th><th>Provider</th>"
        "<th>Quality</th><th>Rows</th></tr>"
    )
    body = header + "".join(rows) + "</table></body></html>"
    path = output_dir / "index.html"
    path.write_text(body, encoding="utf-8")
    return path
