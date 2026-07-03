from __future__ import annotations

import os
from datetime import UTC, datetime

from pydantic import BaseModel

from quant_trade.cloud.config import CloudConfig
from quant_trade.cloud.exceptions import SafetyGateError
from quant_trade.cloud.monitoring import structured_log
from quant_trade.cloud.storage import backend_for_uri


class KillSwitchStatus(BaseModel):
    active: bool = False
    reason: str = ""
    activated_at_utc: str | None = None
    activated_by: str | None = None
    source: str = "none"


def _env_active() -> bool:
    return os.getenv("QUANT_TRADE_GLOBAL_KILL_SWITCH", "").lower() in {"1", "true", "yes", "on"}


def get_kill_switch_status(config: CloudConfig) -> KillSwitchStatus:
    if _env_active():
        st = KillSwitchStatus(
            active=True, reason="environment kill switch", activated_by="env", source="env"
        )
    else:
        storage = backend_for_uri(config.kill_switch_uri)
        st = (
            KillSwitchStatus(source="file")
            if not storage.exists(config.kill_switch_uri)
            else KillSwitchStatus(**storage.read_json(config.kill_switch_uri), source="file")
        )
    structured_log("kill_switch_checked", active=st.active, source=st.source)
    return st


def activate_kill_switch(
    config: CloudConfig, reason: str, actor: str = "manual"
) -> KillSwitchStatus:
    st = KillSwitchStatus(
        active=True,
        reason=reason,
        activated_at_utc=datetime.now(UTC).isoformat(),
        activated_by=actor,
        source="file",
    )
    backend_for_uri(config.kill_switch_uri).write_json(
        config.kill_switch_uri, st.model_dump(exclude={"source"})
    )
    structured_log("kill_switch_activated", reason=reason, actor=actor)
    return st


def clear_kill_switch(config: CloudConfig, reason: str, actor: str = "manual") -> KillSwitchStatus:
    if _env_active():
        raise SafetyGateError("environment kill switch is active and cannot be cleared by CLI")
    st = KillSwitchStatus(
        active=False,
        reason=reason,
        activated_at_utc=datetime.now(UTC).isoformat(),
        activated_by=actor,
        source="file",
    )
    backend_for_uri(config.kill_switch_uri).write_json(
        config.kill_switch_uri, st.model_dump(exclude={"source"})
    )
    structured_log("kill_switch_cleared", reason=reason, actor=actor)
    return st


def assert_not_killed(config: CloudConfig) -> None:
    st = get_kill_switch_status(config)
    if st.active:
        raise SafetyGateError(f"kill switch active: {st.reason}")
