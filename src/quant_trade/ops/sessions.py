from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .exceptions import OpsValidationError

SESSION_STATUSES = {"active", "paused", "retired", "validation_only"}


@dataclass
class PaperOpsSession:
    session_id: str
    display_name: str
    status: str
    strategy_name: str
    strategy_params: dict[str, Any]
    universe: list[str]
    paper_config_path: str
    broker_config_path: str | None = None
    cloud_config_path: str | None = None
    expected_schedule: str = "manual"
    expected_timezone: str = "UTC"
    benchmark: str = "cash"
    owner: str = "research"
    risk_tier: str = "validation"
    max_drawdown_limit: float = 0.2
    max_daily_loss_limit: float = 0.05
    max_rejected_orders: int = 5
    max_stale_heartbeat_minutes: int = 60
    requires_broker_reconciliation: bool = True
    requires_kill_switch_drill: bool = True
    notes: str = ""


@dataclass
class SessionRegistry:
    sessions: list[PaperOpsSession] = field(default_factory=list)


def load_session_registry(path: Path) -> SessionRegistry:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    sessions = [PaperOpsSession(**session) for session in raw.get("sessions", [])]
    return SessionRegistry(sessions=sessions)


def list_sessions(registry: SessionRegistry) -> list[PaperOpsSession]:
    return registry.sessions


def get_session(registry: SessionRegistry, session_id: str) -> PaperOpsSession:
    for session in registry.sessions:
        if session.session_id == session_id:
            return session
    raise OpsValidationError(f"Unknown paper ops session: {session_id}")


def validate_session_config(session: PaperOpsSession) -> None:
    if session.status not in SESSION_STATUSES:
        raise OpsValidationError(f"Invalid session status: {session.status}")
    if not session.session_id or not session.strategy_name or not session.universe:
        raise OpsValidationError("Session requires id, strategy, and universe")
    if session.max_drawdown_limit < 0:
        raise OpsValidationError("Drawdown limit must be non-negative")


def _latest_with_marker(roots: list[Path], session_id: str, marker: str) -> Path | None:
    candidates: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for marker_path in root.rglob(marker):
            if session_id in str(marker_path.parent):
                candidates.append(marker_path.parent)
        for directory in root.rglob(f"*{session_id}*"):
            if directory.is_dir() and (directory / marker).exists():
                candidates.append(directory)
    unique = set(candidates)
    return max(unique, key=lambda path: path.stat().st_mtime) if unique else None


def find_latest_session_artifacts(
    session: PaperOpsSession, artifact_roots: list[Path]
) -> Path | None:
    return _latest_with_marker(artifact_roots, session.session_id, "paper_metrics.json")


def find_latest_state(session: PaperOpsSession, state_roots: list[Path]) -> Path | None:
    return _latest_with_marker(state_roots, session.session_id, "final_state.json")
