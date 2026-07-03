from __future__ import annotations

from datetime import UTC, datetime

from quant_trade.cloud.config import CloudConfig
from quant_trade.cloud.kill_switch import get_kill_switch_status
from quant_trade.cloud.storage import backend_for_uri


def run_health_check(config: CloudConfig) -> dict:
    storage = backend_for_uri(config.artifact_uri)
    probe = f"{config.artifact_uri.rstrip('/')}/health_probe.json"
    payload = {"ok": True, "checked_at_utc": datetime.now(UTC).isoformat()}
    storage.write_json(probe, payload)
    return {
        "ok": True,
        "storage_probe": probe,
        "kill_switch_active": get_kill_switch_status(config).active,
        "clock_utc": payload["checked_at_utc"],
    }
