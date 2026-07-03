from __future__ import annotations

import csv
import json
from pathlib import Path

from quant_trade.security.models import SecurityReport


def write_json(path: Path, report: SecurityReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")


def write_controls_matrix(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        ("Secret scanning", "Local regex/entropy checks", "paper-only"),
        ("Config safety", "Reject live endpoints and real-money approvals", "safe"),
        ("Audit review", "Required fields and secret checks", "reviewed"),
    ]
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["control", "implementation", "status"])
        writer.writerows(rows)


def compliance_markdown() -> str:
    return """# Compliance Notes

This document is not legal advice and not investment advice.

Status: paper-only research/backtesting. `real_money_ready=false`.

## Risk disclaimers

Backtests, paper trading, stress tests, and approvals do not prove future performance.
Data can be incomplete, delayed, adjusted, or wrong.

## Audit evidence summary

Security outputs include secret scan, config safety, audit review, threat model,
controls matrix, and dashboard artifacts.
"""


def threat_model_markdown() -> str:
    return """# Threat Model

Scope: local research and simulated paper-trading artifacts only. No live trading,
live broker endpoints, or secrets are allowed.

## Key threats

- Secret leakage in configs, logs, reports, or artifacts.
- Accidental live endpoint or real-money approval configuration.
- Tampered or incomplete audit evidence.
- Misleading compliance or investment-readiness claims.

## Controls

Local secret scanning, redaction, config safety checks, audit review, paper-only
 documentation, and `real_money_ready=false` reporting.
"""
