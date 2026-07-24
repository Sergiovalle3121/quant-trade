"""Paper-trial readiness V4: executed-drill evidence, not configuration booleans.

A config that *says* ``kill_switch_enabled: true`` proves nothing. Readiness
now requires an artifact per operational drill — actually executed, recorded
with a timestamp, an evidence hash, its result, and an expiry. Two hard rules
close defect G:

- ``broker_mode`` must be explicit (there is no default): a config missing it
  is NOT_READY.
- Configuration booleans without executed-drill artifacts are NOT_READY.

The final status is ``READY_FOR_PAPER_TRIAL`` or ``NOT_READY``. It certifies
operational preparedness for a *supervised paper trial* only: it never claims a
trial ran, and it can never authorize real money. No orders are sent here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quant_trade.carry.quality import parse_utc
from quant_trade.evidence.canonical_json import (
    atomic_write_json,
    canonical_dumps,
    load_json,
    sha256_of_text,
)

READY = "READY_FOR_PAPER_TRIAL"
NOT_READY = "NOT_READY"

#: Every drill that must have been EXECUTED and recorded before a paper trial.
REQUIRED_DRILLS: tuple[str, ...] = (
    "export",
    "heartbeat",
    "kill_switch",
    "recovery",
    "orphan_detection",
    "reconciliation",
    "parity",
)

#: Drills that only count when they actually injected a failure and recovered.
FAILURE_INJECTION_DRILLS: frozenset[str] = frozenset(
    {"kill_switch", "recovery", "orphan_detection"}
)

DEFAULT_DRILL_MAX_AGE_DAYS = 30.0


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
    drill_summary: dict[str, str] = field(default_factory=dict)
    real_money_authorized: bool = False
    trial_days_completed: int = 0  # we never fabricate elapsed days
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "checks": [c.to_dict() for c in self.checks],
            "blocking": self.blocking,
            "drill_summary": self.drill_summary,
            "real_money_authorized": self.real_money_authorized,
            "trial_days_completed": self.trial_days_completed,
            "notes": self.notes,
        }


def record_drill(
    evidence_dir: str | Path,
    *,
    name: str,
    result: str,
    details: dict[str, Any],
    executed_at_utc: str,
    failure_injected: bool = False,
) -> Path:
    """Record one EXECUTED drill as a hashed, timestamped evidence artifact.

    This is the only supported way to produce readiness evidence: run the
    drill (kill the process, trip the kill switch, reconcile the books…), then
    record what actually happened. Recording a drill that was not run is
    falsification — the artifact carries the operator-supplied details and its
    own content hash so review can catch inconsistencies.
    """
    if result not in ("pass", "fail"):
        raise ValueError("result must be 'pass' or 'fail'")
    if name not in REQUIRED_DRILLS:
        raise ValueError(f"unknown drill {name!r}; expected one of {REQUIRED_DRILLS}")
    payload = {
        "schema_version": 1,
        "drill": name,
        "result": result,
        "executed_at_utc": executed_at_utc,
        "failure_injected": bool(failure_injected),
        "details": details,
    }
    payload["evidence_sha256"] = sha256_of_text(canonical_dumps(payload))
    return atomic_write_json(Path(evidence_dir) / f"drill_{name}.json", payload)


def _load_drills(evidence_dir: Path) -> dict[str, dict[str, Any]]:
    drills: dict[str, dict[str, Any]] = {}
    if not evidence_dir.is_dir():
        return drills
    for path in sorted(evidence_dir.glob("drill_*.json")):
        try:
            payload = load_json(path)
        except Exception:  # noqa: BLE001 - unreadable evidence is simply absent
            continue
        if isinstance(payload, dict) and payload.get("drill"):
            drills[str(payload["drill"])] = payload
    return drills


def evaluate_paper_readiness(
    config: dict[str, Any], *, evaluated_at_utc: str | None = None
) -> PaperReadinessReport:
    """Fail-closed readiness from explicit config + executed-drill artifacts."""
    now = evaluated_at_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    checks: list[ReadinessCheck] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append(ReadinessCheck(name, bool(passed), detail))

    add("config_present", bool(config), "a paper-trial config is required")

    # broker_mode is EXPLICIT: no default, and live trading must be off.
    broker_mode = config.get("broker_mode")
    add(
        "broker_is_paper_only",
        broker_mode is not None
        and str(broker_mode).lower() == "paper"
        and not bool(config.get("live_trading", False)),
        "broker_mode must be explicitly 'paper' (no default) and live_trading off",
    )
    add(
        "broker_endpoint_declared",
        bool(str(config.get("broker_endpoint", "")).strip()),
        "the paper broker endpoint must be declared explicitly",
    )

    # Configuration intent (still necessary, never sufficient).
    for key, detail in (
        ("exporter_enabled", "state exporter must be configured"),
        ("recovery_enabled", "crash recovery must be enabled"),
        ("kill_switch_enabled", "kill switch must be enabled"),
        ("orphan_detection_enabled", "orphan-order detection must be enabled"),
        ("reconciliation_enabled", "position/cash reconciliation must be enabled"),
    ):
        add(key, bool(config.get(key, False)), detail)
    add(
        "heartbeat_configured",
        float(config.get("heartbeat_interval_seconds", 0) or 0) > 0,
        "a positive heartbeat interval must be configured",
    )

    # Executed-drill evidence (the part booleans can never replace).
    drill_summary: dict[str, str] = {}
    evidence_dir = Path(str(config.get("drill_evidence_dir", "")) or "/nonexistent")
    drills = _load_drills(evidence_dir)
    max_age_days = float(config.get("drill_max_age_days", DEFAULT_DRILL_MAX_AGE_DAYS))
    for name in REQUIRED_DRILLS:
        record = drills.get(name)
        if record is None:
            drill_summary[name] = "missing"
            add(
                f"drill_{name}_executed",
                False,
                f"no executed-drill artifact for {name!r}; configuration booleans "
                "are not evidence",
            )
            continue
        problems: list[str] = []
        if record.get("result") != "pass":
            problems.append("recorded result is not 'pass'")
        if not str(record.get("evidence_sha256", "")).strip():
            problems.append("artifact carries no evidence hash")
        try:
            age_days = (
                parse_utc(now) - parse_utc(str(record.get("executed_at_utc", "")))
            ).total_seconds() / 86400.0
            if age_days < 0:
                problems.append("drill is dated in the future")
            elif age_days > max_age_days:
                problems.append(f"drill executed {age_days:.0f}d ago (> {max_age_days:.0f}d)")
        except ValueError:
            problems.append("drill timestamp invalid or naive")
        if name in FAILURE_INJECTION_DRILLS and not record.get("failure_injected"):
            problems.append("drill did not inject a real failure; a no-op run proves nothing")
        drill_summary[name] = "ok" if not problems else "; ".join(problems)
        add(
            f"drill_{name}_executed",
            not problems,
            f"executed-drill artifact for {name!r} must be present, passing, hashed, "
            "fresh, and (where applicable) failure-injected",
        )

    blocking = [c.name for c in checks if not c.passed]
    status = READY if not blocking else NOT_READY
    notes = [
        "READY_FOR_PAPER_TRIAL certifies operational prerequisites via executed-drill "
        "evidence; it does not claim any paper trial has run.",
        "This report never authorizes real money.",
    ]
    return PaperReadinessReport(
        status=status,
        checks=checks,
        blocking=blocking,
        drill_summary=drill_summary,
        real_money_authorized=False,
        trial_days_completed=0,
        notes=notes,
    )


def run_parity_drill(evidence_dir: str | Path, *, executed_at_utc: str) -> Path:
    """Execute the parity drill for real and record its artifact.

    Runs the actual parity engine over a real backtest result (backtest vs a
    re-normalisation of itself must reconcile; a cost-perturbed variant must
    diverge). This is a genuine execution, not a boolean.
    """
    from quant_trade.backtest.costs import CostModel
    from quant_trade.backtest.multi_asset import run_multi_asset_backtest
    from quant_trade.data.panel import load_canonical_dataset
    from quant_trade.paper.parity import compare_executions
    from quant_trade.paper.parity_adapters import execution_record_from_backtest
    from quant_trade.research.strategy_registry import get_research_signal_model

    data = load_canonical_dataset("examples/data/sample_multi_asset_ohlcv.csv")
    model = get_research_signal_model("time_series_momentum")
    weights = model.generate(data, {"lookback_days": 20})
    cheap = run_multi_asset_backtest(data, weights, 10_000, CostModel())
    pricey = run_multi_asset_backtest(
        data, weights, 10_000,
        CostModel(percentage_commission=0.01, slippage_bps=20, spread_bps=10),
    )
    same = compare_executions(
        execution_record_from_backtest(cheap, source="backtest"),
        execution_record_from_backtest(cheap, source="simulated_paper"),
    )
    different = compare_executions(
        execution_record_from_backtest(cheap, source="backtest"),
        execution_record_from_backtest(pricey, source="simulated_paper"),
    )
    passed = same.reconciled and not different.reconciled
    return record_drill(
        evidence_dir,
        name="parity",
        result="pass" if passed else "fail",
        executed_at_utc=executed_at_utc,
        failure_injected=False,
        details={
            "identical_run_reconciled": same.reconciled,
            "perturbed_run_diverged": not different.reconciled,
            "equity_drift_perturbed": different.equity_drift,
        },
    )


def generate_paper_runbook(report: PaperReadinessReport) -> str:
    """Markdown runbook + manual pre-flight checklist, drill-evidence based."""
    lines = [
        "# Paper Trial Runbook",
        "",
        f"Readiness status: **{report.status}**  ·  Real money: **NO-GO**",
        "",
        "## Pre-flight checklist (executed drills, not booleans)",
    ]
    for c in report.checks:
        mark = "x" if c.passed else " "
        lines.append(f"- [{mark}] {c.name}: {c.detail}")
    lines += [
        "",
        "## How to produce drill evidence",
        "Each drill must be RUN, then recorded with `record_drill` (or the",
        "readiness-evidence CLI). Kill-switch / recovery / orphan drills must",
        "inject a real failure (kill the process mid-run, trip the switch,",
        "orphan an order) — a no-op run proves nothing. Artifacts expire and",
        "must be re-executed periodically.",
        "",
        "## Abort conditions",
        "- Reconciliation drift beyond tolerance, missed heartbeats, orphan orders.",
        "- Any attempt to route a real-money order (must be impossible by config).",
    ]
    if report.blocking:
        lines += ["", "## Blocking issues", *[f"- {b}" for b in report.blocking]]
    return "\n".join(lines) + "\n"
