"""Read-only mining telemetry, inventory, alerts, and watch-only reconciliation.

This module *reads* rig state and *reconciles* observed wallet payouts against
expectations. It defines no method that starts, stops, tunes, or otherwise
controls hardware, and no method that signs a transaction. The three safety
constants below are hard-wired off and are asserted by tests; any future
CGMiner/Braiins integration must implement the read-only adapter protocol only.
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

# Non-negotiable safety posture. These are constants, not config, on purpose.
AUTHORIZED_TO_START_MINER = False
HARDWARE_CONTROL_ENABLED = False
WALLET_SIGNING_ENABLED = False


def redact_serial(serial: str) -> str:
    """Keep only the last 4 chars of a serial for logs/inventory."""
    s = str(serial)
    return ("*" * max(0, len(s) - 4)) + s[-4:] if s else ""


@dataclass(frozen=True)
class RigInventoryItem:
    rig_id: str
    redacted_serial: str
    facility: str
    rack: str
    algorithm: str
    rated_hashrate_ths: float
    rated_watts: float

    def __post_init__(self) -> None:
        if not self.rig_id.strip():
            raise ValueError("rig_id is required")
        if self.rated_hashrate_ths <= 0 or self.rated_watts <= 0:
            raise ValueError("rated hashrate and watts must be > 0")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TelemetrySample:
    rig_id: str
    captured_at_utc: str
    hashrate_ths: float
    power_watts: float
    temperature_c: float
    fan_rpm: float
    reject_rate: float
    uptime_rate: float
    last_seen_utc: str
    staleness_seconds: float = 0.0

    def __post_init__(self) -> None:
        for name in ("hashrate_ths", "power_watts", "fan_rpm", "staleness_seconds"):
            v = getattr(self, name)
            if not math.isfinite(v) or v < 0:
                raise ValueError(f"{name} must be finite and >= 0")
        if not 0 <= self.reject_rate <= 1:
            raise ValueError("reject_rate must be in [0, 1]")
        if not 0 <= self.uptime_rate <= 1:
            raise ValueError("uptime_rate must be in [0, 1]")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TelemetryAdapter(Protocol):
    """Read-only telemetry source. Implementations MUST expose no control verbs."""

    def read(self, rig_id: str) -> TelemetrySample:
        ...


class FakeTelemetryAdapter:
    """Offline adapter for tests; serves preloaded samples."""

    def __init__(self, samples: dict[str, TelemetrySample]) -> None:
        self._samples = samples

    def read(self, rig_id: str) -> TelemetrySample:
        if rig_id not in self._samples:
            raise ValueError(f"no telemetry for {rig_id!r}")
        return self._samples[rig_id]


def load_samples_from_records(records: list[dict[str, Any]]) -> list[TelemetrySample]:
    known = {f for f in TelemetrySample.__dataclass_fields__}
    return [TelemetrySample(**{k: v for k, v in r.items() if k in known}) for r in records]


def load_samples_from_csv(path: str | Path) -> list[TelemetrySample]:
    with Path(path).open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    parsed: list[dict[str, Any]] = []
    numeric = {
        "hashrate_ths",
        "power_watts",
        "temperature_c",
        "fan_rpm",
        "reject_rate",
        "uptime_rate",
        "staleness_seconds",
    }
    for row in rows:
        parsed.append({k: (float(v) if k in numeric and v != "" else v) for k, v in row.items()})
    return load_samples_from_records(parsed)


class AlertSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass
class MiningAlert:
    code: str
    severity: AlertSeverity
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "severity": str(self.severity), "message": self.message}


@dataclass(frozen=True)
class AlertThresholds:
    max_temperature_c: float = 80.0
    min_hashrate_fraction: float = 0.85  # of rated
    max_power_fraction: float = 1.15  # of rated
    max_reject_rate: float = 0.02
    max_staleness_seconds: float = 600.0


def evaluate_alerts(
    sample: TelemetrySample,
    inventory: RigInventoryItem,
    thresholds: AlertThresholds,
    *,
    net_daily_profit_usd: float | None = None,
    payout_mismatch: bool = False,
) -> list[MiningAlert]:
    """Local, read-only alerting. Produces alerts; never acts on hardware."""
    alerts: list[MiningAlert] = []
    if sample.temperature_c > thresholds.max_temperature_c:
        alerts.append(
            MiningAlert(
                "over_temperature",
                AlertSeverity.CRITICAL,
                f"{sample.temperature_c:.0f}C > {thresholds.max_temperature_c:.0f}C",
            )
        )
    if sample.hashrate_ths < inventory.rated_hashrate_ths * thresholds.min_hashrate_fraction:
        alerts.append(
            MiningAlert(
                "hashrate_drop",
                AlertSeverity.WARNING,
                f"{sample.hashrate_ths:.1f} TH/s below "
                f"{thresholds.min_hashrate_fraction:.0%} of rated",
            )
        )
    if sample.power_watts > inventory.rated_watts * thresholds.max_power_fraction:
        alerts.append(
            MiningAlert("power_anomaly", AlertSeverity.WARNING, f"{sample.power_watts:.0f}W high")
        )
    if sample.staleness_seconds > thresholds.max_staleness_seconds:
        alerts.append(
            MiningAlert(
                "stale_telemetry",
                AlertSeverity.WARNING,
                f"telemetry {sample.staleness_seconds:.0f}s old",
            )
        )
    if sample.reject_rate > thresholds.max_reject_rate:
        alerts.append(
            MiningAlert(
                "reject_rate_spike",
                AlertSeverity.WARNING,
                f"reject rate {sample.reject_rate:.1%}",
            )
        )
    if net_daily_profit_usd is not None and net_daily_profit_usd < 0:
        alerts.append(
            MiningAlert(
                "negative_economics",
                AlertSeverity.CRITICAL,
                f"net daily profit ${net_daily_profit_usd:.2f} < 0",
            )
        )
    if payout_mismatch:
        alerts.append(
            MiningAlert("payout_mismatch", AlertSeverity.WARNING, "payout differs from expectation")
        )
    return alerts


@dataclass
class ReconciliationResult:
    expected_coin: float
    observed_coin: float
    absolute_diff: float
    relative_diff: float
    within_tolerance: bool
    wallet_is_watch_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def reconcile_payouts(
    expected_coin: float, observed_coin: float, *, tolerance: float = 0.05
) -> ReconciliationResult:
    """Watch-only reconciliation of observed wallet payouts vs expectation.

    The wallet is observe-only: this compares numbers and never signs or moves
    funds (WALLET_SIGNING_ENABLED is False).
    """
    if expected_coin < 0 or observed_coin < 0:
        raise ValueError("payout amounts must be >= 0")
    diff = abs(observed_coin - expected_coin)
    rel = diff / expected_coin if expected_coin > 0 else (0.0 if observed_coin == 0 else 1.0)
    return ReconciliationResult(
        expected_coin=expected_coin,
        observed_coin=observed_coin,
        absolute_diff=diff,
        relative_diff=rel,
        within_tolerance=rel <= tolerance,
    )


@dataclass
class OperatingLedgerEntry:
    date: str
    rig_id: str
    energy_kwh: float
    electricity_cost_usd: float
    coin_mined: float
    payout_coin: float
    net_usd: float
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DailyOperatingLedger:
    entries: list[OperatingLedgerEntry] = field(default_factory=list)

    def add(self, entry: OperatingLedgerEntry) -> None:
        self.entries.append(entry)

    def total_net_usd(self) -> float:
        return sum(e.net_usd for e in self.entries)

    def to_records(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self.entries]

    def write_json(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_records(), indent=2), encoding="utf-8")
        return p


def safety_posture() -> dict[str, bool]:
    """The read-only posture, for logging into any report."""
    return {
        "authorized_to_start_miner": AUTHORIZED_TO_START_MINER,
        "hardware_control_enabled": HARDWARE_CONTROL_ENABLED,
        "wallet_signing_enabled": WALLET_SIGNING_ENABLED,
    }
