from __future__ import annotations

from pathlib import Path

from quant_trade.approvals.models import ApprovalRequest


def write_dashboard(path: Path, requests: list[ApprovalRequest]) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    rows = "".join(
        f"<tr><td>{r.approval_id}</td><td>{r.request_type}</td><td>{r.status}</td><td>false</td></tr>"
        for r in requests
    )
    (path / "index.html").write_text(
        (
            "<html><body><h1>Approval Dashboard</h1>"
            f"<p>Paper-only controls.</p><table>{rows}</table></body></html>"
        ),
        encoding="utf-8",
    )
    return path
