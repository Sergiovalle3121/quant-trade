"""Safety drills that actually exercise the mechanisms they claim to test.

A drill that unconditionally returns "pass" is worse than no drill: it
manufactures confidence. Each drill here performs the real action in an
isolated temporary environment and reports what actually happened.
"""

from __future__ import annotations

import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .config import OpsConfig, validate_ops_config
from .reports import write_json, write_md


@dataclass
class DrillResult:
    name: str
    status: str
    details: str


def kill_switch_drill(cfg: OpsConfig) -> DrillResult:
    """Activate a kill switch in a temp location and assert the gate raises."""
    del cfg
    from quant_trade.cloud.config import CloudConfig
    from quant_trade.cloud.exceptions import SafetyGateError
    from quant_trade.cloud.kill_switch import activate_kill_switch, assert_not_killed

    with tempfile.TemporaryDirectory() as tmp:
        cloud_cfg = CloudConfig(
            deployment_name="drill",
            artifact_uri=f"{tmp}/artifacts",
            state_uri=f"{tmp}/state",
            heartbeat_uri=f"{tmp}/heartbeat.json",
            kill_switch_uri=f"{tmp}/kill_switch.json",
        )
        activate_kill_switch(cloud_cfg, reason="drill", actor="drill")
        try:
            assert_not_killed(cloud_cfg)
        except SafetyGateError:
            return DrillResult(
                "kill_switch_drill", "pass", "Activated kill switch blocked the gate."
            )
    return DrillResult(
        "kill_switch_drill", "fail", "Gate did NOT raise with an active kill switch."
    )


def stale_heartbeat_drill(cfg: OpsConfig) -> DrillResult:
    """Write an old heartbeat and assert staleness detection fires."""
    del cfg
    from quant_trade.cloud.heartbeat import Heartbeat, is_stale

    old = Heartbeat(
        deployment_name="drill",
        job_name="drill",
        run_id="drill",
        status="running",
        started_at_utc=datetime.now(UTC).isoformat(),
        last_update_utc=(datetime.now(UTC) - timedelta(hours=2)).isoformat(),
        mode="dry_run",
        broker_provider="simulated",
        paper_submission_enabled=False,
        kill_switch_active=False,
    )
    fresh = Heartbeat(
        deployment_name="drill",
        job_name="drill",
        run_id="drill",
        status="running",
        started_at_utc=datetime.now(UTC).isoformat(),
        mode="dry_run",
        broker_provider="simulated",
        paper_submission_enabled=False,
        kill_switch_active=False,
    )
    if is_stale(old, threshold_minutes=30) and not is_stale(fresh, threshold_minutes=30):
        return DrillResult(
            "stale_heartbeat_drill", "pass", "2h-old heartbeat detected as stale; fresh one not."
        )
    return DrillResult("stale_heartbeat_drill", "fail", "Staleness detection is broken.")


def missing_artifact_drill(cfg: OpsConfig) -> DrillResult:
    """Validate an empty run dir and assert validation fails."""
    del cfg
    from quant_trade.ops.validation import validate_artifacts

    with tempfile.TemporaryDirectory() as tmp:
        report = validate_artifacts(Path(tmp), "drill")
        status = getattr(report, "status", None) or (
            report.get("status") if isinstance(report, dict) else None
        )
        if status and str(status) != "pass":
            return DrillResult(
                "missing_artifact_drill", "pass", "Empty run dir failed validation as expected."
            )
    return DrillResult(
        "missing_artifact_drill", "fail", "Validation passed an empty run dir."
    )


def live_endpoint_rejection_drill(cfg: OpsConfig) -> DrillResult:
    original = cfg.allow_live_trading
    try:
        cfg.allow_live_trading = True
        validate_ops_config(cfg)
    except Exception:
        return DrillResult("live_endpoint_rejection_drill", "pass", "Unsafe live flag rejected.")
    finally:
        cfg.allow_live_trading = original
    return DrillResult("live_endpoint_rejection_drill", "fail", "Unsafe config was not rejected.")


def lock_contention_drill(cfg: OpsConfig) -> DrillResult:
    """Acquire the same lock twice and assert the second acquisition fails."""
    del cfg
    from quant_trade.cloud.exceptions import LockError
    from quant_trade.cloud.locks import LocalFileLock

    with tempfile.TemporaryDirectory() as tmp:
        lock = LocalFileLock(Path(tmp))
        lock.acquire_lock("drill", "runner-1", ttl_minutes=5)
        try:
            lock.acquire_lock("drill", "runner-2", ttl_minutes=5)
        except LockError:
            return DrillResult(
                "lock_contention_drill", "pass", "Second acquisition failed closed."
            )
    return DrillResult("lock_contention_drill", "fail", "Held lock was acquired twice.")


def run_all_drills(cfg: OpsConfig) -> list[DrillResult]:
    return [
        kill_switch_drill(cfg),
        stale_heartbeat_drill(cfg),
        missing_artifact_drill(cfg),
        live_endpoint_rejection_drill(cfg),
        lock_contention_drill(cfg),
    ]


def generate_drill_report(results: list[DrillResult], out: Path) -> None:
    payload = [asdict(result) for result in results]
    write_json(out / "drill_results.json", payload)
    write_md(out / "drill_results.md", "Safety Drill Results", {"results": payload})
