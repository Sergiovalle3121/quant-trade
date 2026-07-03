from __future__ import annotations

from pathlib import Path

from quant_trade.campaigns.models import RankedCandidate


def write_dashboard(path: Path, ranked: list[RankedCandidate]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = "\n".join(_row(r) for r in ranked)
    html = f"""
<!doctype html>
<html><head><title>Campaign Dashboard</title></head>
<body>
<h1>Research Campaign Dashboard</h1>
<p>Paper/research only; not real-money readiness.</p>
<table>
<thead><tr><th>Run</th><th>Strategy</th><th>Composite</th><th>Rejected</th><th>Reason</th></tr></thead>
<tbody>{rows}</tbody>
</table>
</body></html>
"""
    path.write_text(html, encoding="utf-8")


def _row(candidate: RankedCandidate) -> str:
    return (
        f"<tr><td>{candidate.run_id}</td><td>{candidate.strategy}</td>"
        f"<td>{candidate.composite_score:.4f}</td><td>{candidate.rejected}</td>"
        f"<td>{candidate.rejection_reason}</td></tr>"
    )
