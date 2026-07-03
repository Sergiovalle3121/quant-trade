from __future__ import annotations

from pathlib import Path

from quant_trade.security.models import Finding, SecurityReport


def check_config_safety(paths: list[Path] | None = None) -> SecurityReport:
    roots = paths or [
        Path("configs"),
        Path("deploy"),
        Path(".github/workflows"),
        Path("outputs/trials"),
    ]
    files: list[Path] = []
    suffixes = {".yaml", ".yml", ".json", ".tf"}
    for root in roots:
        if root.is_file():
            files.append(root)
        elif root.exists():
            files.extend(p for p in root.rglob("*") if p.suffix in suffixes)
    findings: list[Finding] = []
    for path in files:
        low = path.read_text(encoding="utf-8", errors="ignore").lower()
        live_alpaca = "https://api.alpaca.markets" in low
        live_hint = all(x in low for x in ("alpaca", "endpoint", "live"))
        if live_alpaca or ("paper-api.alpaca.markets" not in low and live_hint):
            findings.append(Finding("live_broker_endpoint", "critical", str(path), 1, "Prohibited"))
        if "real_money_approved: true" in low or '"real_money_approved": true' in low:
            findings.append(Finding("real_money_approval", "critical", str(path), 1, "Prohibited"))
        if "allow_live_trading: true" in low or "live_trading: true" in low:
            findings.append(Finding("live_trading_enabled", "critical", str(path), 1, "Prohibited"))
        workflow = path.parts[:2] == (".github", "workflows")
        if workflow and "deploy" in low and "workflow_dispatch" not in low:
            findings.append(Finding("deploy_workflow_dispatch", "high", str(path), 1, "Required"))
        if path.suffix == ".tf" and "paper_submit" in low and "default     = true" in low:
            findings.append(Finding("terraform_submit_default", "critical", str(path), 1, "Unsafe"))
    return SecurityReport(status="fail" if findings else "pass", findings=findings)
