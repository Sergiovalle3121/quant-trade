"""Mining market evidence: sourced snapshots, dimensional units, raw benchmarks.

Three disciplines close V6 defect O:

1. **Market snapshots, never inline numbers.** A hashprice typed into YAML is
   not evidence. `MarketSnapshot` requires source, capture time, and the
   SHA-256 of the raw response it was normalized from; freshness is
   recomputed, and a second source's divergence is reported when available.
2. **Dimensional hashrate units.** Every algorithm declares its own unit and
   revenue model; converting KHeavyHash to USD/TH/day silently priced apples
   in orange units. SHA-256 on rented GPUs is INCOMPATIBLE_OR_UNBENCHMARKED —
   BTC needs permitted ASIC capacity, which no current provider policy allows.
3. **Benchmarks reconstructed from raw logs.** The importer re-parses the raw
   miner log and cross-checks every claimed number; a YAML that disagrees
   with its own log is rejected.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from quant_trade.carry.quality import parse_utc
from quant_trade.evidence.canonical_json import sha256_of_file

ALGORITHM_UNIT_REGISTRY_VERSION = "1"


@dataclass(frozen=True)
class AlgorithmUnitDefinition:
    """Versioned dimensional contract for one mining algorithm."""

    algorithm_id: str
    coin: str
    network: str
    native_unit: str
    hashes_per_unit: Decimal
    device_capacity_source: str
    revenue_model: str
    period: str = "day"
    currency: str = "USD"
    asic_only: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "registry_version": ALGORITHM_UNIT_REGISTRY_VERSION,
            "algorithm_id": self.algorithm_id,
            "coin": self.coin,
            "network": self.network,
            "native_unit": self.native_unit,
            # Backward-compatible name used by V6 callers.
            "hashrate_unit": self.native_unit,
            "hashes_per_unit": self.hashes_per_unit,
            "normalized_hashes_per_second": self.hashes_per_unit,
            "device_capacity_source": self.device_capacity_source,
            "revenue_model": self.revenue_model,
            "period": self.period,
            "currency": self.currency,
            "asic_only": self.asic_only,
            "coin_examples": (self.coin,),
        }


#: Per-algorithm dimensional metadata. Decimal prevents binary-float unit drift.
ALGORITHM_UNITS: dict[str, AlgorithmUnitDefinition] = {
    "sha256": AlgorithmUnitDefinition(
        algorithm_id="sha256",
        coin="BTC",
        network="bitcoin-mainnet",
        native_unit="TH/s",
        hashes_per_unit=Decimal("1000000000000"),
        device_capacity_source="exact_sku_benchmark",
        revenue_model="hashprice_usd_per_th_day",
        asic_only=True,
    ),
    "kheavyhash": AlgorithmUnitDefinition(
        algorithm_id="kheavyhash",
        coin="KAS",
        network="kaspa-mainnet",
        native_unit="GH/s",
        hashes_per_unit=Decimal("1000000000"),
        device_capacity_source="exact_sku_benchmark",
        revenue_model="hashprice_usd_per_gh_day",
    ),
    "etchash": AlgorithmUnitDefinition(
        algorithm_id="etchash",
        coin="ETC",
        network="ethereum-classic-mainnet",
        native_unit="MH/s",
        hashes_per_unit=Decimal("1000000"),
        device_capacity_source="exact_sku_benchmark",
        revenue_model="hashprice_usd_per_mh_day",
    ),
}


def algorithm_unit(algorithm_id: str) -> dict[str, Any]:
    meta = ALGORITHM_UNITS.get(algorithm_id.strip().lower())
    if meta is None:
        raise ValueError(
            f"unknown algorithm {algorithm_id!r}; refusing to guess its hashrate "
            f"unit (known: {sorted(ALGORITHM_UNITS)})"
        )
    return meta.to_dict()


def native_hashrate_units(algorithm_id: str, hashrate_hs: float) -> Decimal:
    """Convert physical H/s into the algorithm's declared native unit."""
    if not math.isfinite(hashrate_hs) or hashrate_hs <= 0:
        raise ValueError("hashrate_hs must be finite and > 0")
    hashes_per_unit = algorithm_unit(algorithm_id)["hashes_per_unit"]
    assert isinstance(hashes_per_unit, Decimal)
    return Decimal(str(hashrate_hs)) / hashes_per_unit


def check_algorithm_hardware(algorithm_id: str, architecture: str) -> str | None:
    """Problem string when the algorithm cannot be benchmarked on the hardware."""
    meta = algorithm_unit(algorithm_id)
    if meta["asic_only"] and architecture != "asic":
        return (
            f"{algorithm_id} on {architecture} is INCOMPATIBLE_OR_UNBENCHMARKED: "
            "competitive hashing needs ASIC capacity, and no current provider "
            "policy permits it"
        )
    return None


@dataclass(frozen=True)
class MarketSnapshot:
    """A sourced, fresh, byte-bound market observation for one algorithm/coin."""

    algorithm_id: str
    coin: str
    hashrate_unit: str
    hashprice_usd_per_unit_day: float
    coin_price_usd: float
    source_name: str
    source_url: str
    captured_at_utc: str
    raw_sha256: str
    network: str = ""
    network_difficulty: float = 0.0
    pool_fee_rate: float = 0.01
    fx_source: str = "USD"
    second_source_name: str = ""
    second_source_value: float | None = None
    max_age_hours: float = 24.0

    def __post_init__(self) -> None:
        unit_contract = algorithm_unit(self.algorithm_id)
        expected_unit = unit_contract["hashrate_unit"]
        if self.hashrate_unit != expected_unit:
            raise ValueError(
                f"{self.algorithm_id} is priced in {expected_unit}, not "
                f"{self.hashrate_unit!r} — cross-unit pricing is forbidden"
            )
        if self.coin.upper() != str(unit_contract["coin"]).upper():
            raise ValueError(
                f"{self.algorithm_id} is registered for {unit_contract['coin']}, not {self.coin!r}"
            )
        if self.network != unit_contract["network"]:
            raise ValueError(
                f"{self.algorithm_id} is registered for network "
                f"{unit_contract['network']}, not {self.network!r}"
            )
        for name in ("hashprice_usd_per_unit_day", "coin_price_usd"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and > 0")
        if not self.source_name.strip() or not self.source_url.strip():
            raise ValueError("market snapshots require an attributable source")
        if not self.raw_sha256.strip():
            raise ValueError(
                "market snapshots require the SHA-256 of the raw response; an "
                "inline number without raw bytes is not evidence"
            )
        if not self.captured_at_utc.strip():
            raise ValueError("captured_at_utc is required")

    @property
    def source_divergence(self) -> float | None:
        if self.second_source_value is None:
            return None
        return abs(self.second_source_value - self.hashprice_usd_per_unit_day) / (
            self.hashprice_usd_per_unit_day
        )

    def freshness_problems(self, *, evaluated_at_utc: str) -> list[str]:
        try:
            age_h = (
                parse_utc(evaluated_at_utc) - parse_utc(self.captured_at_utc)
            ).total_seconds() / 3600.0
        except ValueError as exc:
            return [f"market snapshot timestamps invalid: {exc}"]
        if age_h < 0:
            return ["market snapshot is dated in the future"]
        if age_h > self.max_age_hours:
            return [f"market snapshot {age_h:.1f}h old exceeds max age {self.max_age_hours:.0f}h"]
        return []

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_market_snapshot(path: str | Path) -> MarketSnapshot:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    known = {f for f in MarketSnapshot.__dataclass_fields__}
    return MarketSnapshot(**{k: v for k, v in payload.items() if k in known})


def verify_market_snapshot_bytes(
    snapshot: MarketSnapshot, raw_artifact_path: str | Path | None
) -> list[str]:
    """Open and hash the raw response claimed by a normalized snapshot."""
    if raw_artifact_path is None:
        return ["market raw response bytes unavailable; raw_sha256 cannot be byte-verified"]
    path = Path(raw_artifact_path)
    if not path.exists():
        return [f"market raw response missing on disk: {raw_artifact_path}"]
    actual = sha256_of_file(path)
    if actual != snapshot.raw_sha256:
        return ["market raw response bytes do NOT hash to the snapshot raw_sha256"]
    return []


def parse_benchmark_log(raw: bytes) -> dict[str, Any]:
    """Reconstruct benchmark facts from the raw log (structured JSON lines).

    Expected line kinds: ``{"event": "config", ...}``, ``{"event": "sample",
    "hashrate": x, "t": seconds}``, ``{"event": "share", "accepted": bool}``,
    ``{"event": "end", "duration_seconds": d, "warmup_seconds": w}``.
    """
    samples: list[float] = []
    accepted = rejected = 0
    duration = warmup = 0.0
    restarts = 0
    config: dict[str, Any] = {}
    for line in raw.decode("utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        kind = event.get("event")
        if kind == "config":
            config = {k: v for k, v in event.items() if k != "event"}
        elif kind == "sample":
            samples.append(float(event["hashrate"]))
        elif kind == "share":
            if event.get("accepted"):
                accepted += 1
            else:
                rejected += 1
        elif kind == "restart":
            restarts += 1
        elif kind == "end":
            duration = float(event.get("duration_seconds", 0.0))
            warmup = float(event.get("warmup_seconds", 0.0))
    if not samples or duration <= 0:
        raise ValueError("benchmark log carries no usable samples/duration")
    stable = samples[len(samples) // 4 :]  # skip warm-up quartile
    return {
        "hashrate_hs": sum(stable) / len(stable),
        "duration_seconds": duration,
        "warmup_seconds": warmup,
        "shares_accepted": accepted,
        "shares_rejected": rejected,
        "restarts": restarts,
        "config": config,
        "samples": len(samples),
    }


def verify_benchmark_against_log(
    claimed: dict[str, Any], raw: bytes, *, tolerance: float = 0.05
) -> list[str]:
    """Cross-check claimed benchmark numbers against the reconstructed log."""
    problems: list[str] = []
    try:
        rebuilt = parse_benchmark_log(raw)
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        return [f"benchmark log unusable: {exc}"]
    claimed_rate = float(claimed.get("hashrate_hs", 0.0))
    if claimed_rate <= 0:
        problems.append("claimed hashrate_hs missing or non-positive")
    elif abs(claimed_rate - rebuilt["hashrate_hs"]) > tolerance * rebuilt["hashrate_hs"]:
        problems.append(
            f"claimed hashrate {claimed_rate:.3e} differs from the log's "
            f"{rebuilt['hashrate_hs']:.3e} by more than {tolerance:.0%}"
        )
    for field_name in ("duration_seconds", "shares_accepted", "shares_rejected"):
        if field_name in claimed and float(claimed[field_name]) != float(rebuilt[field_name]):
            problems.append(
                f"claimed {field_name}={claimed[field_name]} does not match the "
                f"log's {rebuilt[field_name]}"
            )
    return problems
