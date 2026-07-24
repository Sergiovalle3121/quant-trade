"""Paper-trial readiness V3.

Checks that the *operational* prerequisites for a supervised paper trial are in
place — validated config, exporter, recovery, kill switch, orphan detection,
heartbeat, reconciliation, and a paper-only broker. It does NOT claim any trial
has run: the final status is ``READY_FOR_PAPER_TRIAL`` or ``NOT_READY``, and the
report can never authorize real money.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

READY = "READY_FOR_PAPER_TRIAL"
NOT_READY = "NOT_READY"


@dataclass
class ReadinessCheck:
    name: str
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PaperReadinessReport:
    status: str  # READY_FOR_PAPER_TRIAL | NOT_READY
    checks: list[ReadinessCheck]
    blocking: list[str]
    real_money_authorized: bool = False
    trial_days_completed: int = 0  # we never fabricate elapsed days
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "checks": [c.to_dict() for c in self.checks],
            "blocking": self.blocking,
            "real_money_authorized": self.real_money_authorized,
            "trial_days_completed": self.trial_days_completed,
            "notes": self.notes,
        }


def evaluate_paper_readiness(config: dict[str, Any]) -> PaperReadinessReport:
    """Evaluate operational readiness from a paper-trial config (fail closed)."""
    checks: list[ReadinessCheck] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append(ReadinessCheck(name, bool(passed), detail))

    add("config_present", bool(config), "a paper-trial config is required")
    add(
        "broker_is_paper_only",
        str(config.get("broker_mode", "paper")).lower() == "paper"
        and not bool(config.get("live_trading", False)),
        "broker must be paper-only; live trading must be off",
    )
    add("exporter_configured", bool(config.get("exporter_enabled", False)),
        "state exporter must be configured")
    add("recovery_enabled", bool(config.get("recovery_enabled", False)),
        "crash recovery must be enabled")
    add("kill_switch_enabled", bool(config.get("kill_switch_enabled", False)),
        "kill switch must be enabled")
    add("orphan_detection_enabled", bool(config.get("orphan_detection_enabled", False)),
        "orphan-order detection must be enabled")
    add(
        "heartbeat_configured",
        float(config.get("heartbeat_interval_seconds", 0) or 0) > 0,
        "a positive heartbeat interval must be configured",
    )
    add("reconciliation_enabled", bool(config.get("reconciliation_enabled", False)),
        "position/cash reconciliation must be enabled")

    blocking = [c.name for c in checks if not c.passed]
    status = READY if not blocking else NOT_READY
    notes = [
        "READY_FOR_PAPER_TRIAL certifies operational prerequisites only; it does "
        "not claim any paper trial has run.",
        "This report never authorizes real money.",
    ]
    return PaperReadinessReport(
        status=status,
        checks=checks,
        blocking=blocking,
        real_money_authorized=False,
        trial_days_completed=0,
        notes=notes,
    )


def generate_paper_runbook(report: PaperReadinessReport) -> str:
    """Produce a markdown runbook + manual pre-flight checklist."""
    lines = [
        "# Paper Trial Runbook",
        "",
        f"Readiness status: **{report.status}**  ·  Real money: **NO-GO**",
        "",
        "## Pre-flight checklist (manual)",
    ]
    for c in report.checks:
        mark = "x" if c.passed else " "
        lines.append(f"- [{mark}] {c.name}: {c.detail}")
    lines += [
        "",
        "## Operating procedure",
        "1. Confirm the broker credentials point at the PAPER endpoint only.",
        "2. Start the heartbeat monitor; verify it reports within the interval.",
        "3. Run one dry rebalance; reconcile positions and cash against the broker.",
        "4. Verify the kill switch halts trading and flattens intent (paper).",
        "5. Kill the process mid-run; verify recovery restores state and detects orphans.",
        "6. Only after a full supervised trial window, review evidence — never flip to live.",
        "",
        "## Abort conditions",
        "- Reconciliation drift beyond tolerance, missed heartbeats, or orphan orders.",
        "- Any attempt to route a real-money order (must be impossible by config).",
    ]
    if report.blocking:
        lines += ["", "## Blocking issues", *[f"- {b}" for b in report.blocking]]
    return "\n".join(lines) + "\n"
