"""Read-only data layer for carry research: contracts, validation, fixtures.

Real venue access lives behind an adapter with a timeout, limited retries, and a
staleness field; the adapter is imported lazily so the package stays importable
(and CI stays green) without exchange libraries. Tests run entirely offline
against JSON fixtures or the deterministic synthetic generator.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Protocol

from quant_trade.carry.models import CarrySnapshot

REQUIRED_FIELDS = (
    "symbol",
    "exchange",
    "captured_at_utc",
    "spot_price",
    "perp_mark_price",
    "perp_index_price",
    "realized_funding_rate",
)


class CarryDataAdapter(Protocol):
    """A read-only source of carry snapshots. Implementations MUST NOT trade."""

    def fetch_snapshots(self, symbol: str, exchange: str) -> list[CarrySnapshot]:
        ...


def validate_snapshot_record(record: dict[str, Any]) -> list[str]:
    """Return a list of schema problems (empty = valid)."""
    errors: list[str] = []
    for field_name in REQUIRED_FIELDS:
        if field_name not in record:
            errors.append(f"missing required field: {field_name}")
    for numeric in (
        "spot_price",
        "perp_mark_price",
        "perp_index_price",
        "realized_funding_rate",
    ):
        if numeric in record:
            value = record[numeric]
            if not isinstance(value, int | float) or not math.isfinite(float(value)):
                errors.append(f"{numeric} must be a finite number")
    source = record.get("data_source", "synthetic")
    if source not in ("synthetic", "real"):
        errors.append("data_source must be 'synthetic' or 'real'")
    # A predicted funding rate must never be aliased to the realized field.
    if (
        "predicted_funding_rate" in record
        and "realized_funding_rate" in record
        and record["predicted_funding_rate"] is record["realized_funding_rate"]
        and record["predicted_funding_rate"] is not None
    ):
        errors.append("predicted and realized funding must be distinct values")
    return errors


def load_snapshots_from_records(records: list[dict[str, Any]]) -> list[CarrySnapshot]:
    """Validate and materialise snapshots from plain dicts (fail closed)."""
    snapshots: list[CarrySnapshot] = []
    for i, record in enumerate(records):
        problems = validate_snapshot_record(record)
        if problems:
            raise ValueError(f"record {i} invalid: {'; '.join(problems)}")
        known = {f for f in CarrySnapshot.__dataclass_fields__}
        snapshots.append(CarrySnapshot(**{k: v for k, v in record.items() if k in known}))
    return snapshots


def load_snapshots_from_json(path: str | Path) -> list[CarrySnapshot]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    records = payload["snapshots"] if isinstance(payload, dict) else payload
    return load_snapshots_from_records(records)


def synthetic_funding_snapshots(
    *,
    symbol: str = "BTC",
    exchange: str = "synthetic_venue",
    periods: int = 180,
    funding_interval_hours: float = 8.0,
    seed: int = 7,
    base_funding_rate: float = 0.00008,
    funding_ar_coef: float = 0.7,
    funding_noise: float = 0.00005,
) -> list[CarrySnapshot]:
    """Deterministic, plausible-but-synthetic funding snapshots.

    Funding follows a mean-reverting AR(1) around a small positive rate with
    occasional sign flips; the perp basis is loosely tied to funding. This is a
    *contract exerciser*, not a profitable campaign — ``data_source='synthetic'``
    guarantees the research layer can never emit GO from it.
    """
    import numpy as np  # local import keeps module import light

    rng = np.random.default_rng(seed)
    snapshots: list[CarrySnapshot] = []
    spot = 30000.0
    funding = base_funding_rate
    start = np.datetime64("2024-01-01T00:00:00")
    for i in range(periods):
        spot *= float(1 + rng.normal(0.0, 0.01))
        funding = (
            base_funding_rate
            + funding_ar_coef * (funding - base_funding_rate)
            + float(rng.normal(0.0, funding_noise))
        )
        basis = funding * 3.0 + float(rng.normal(0.0, 0.0005))
        perp_mark = spot * (1 + basis)
        ts = start + np.timedelta64(int(i * funding_interval_hours), "h")
        snapshots.append(
            CarrySnapshot(
                symbol=symbol,
                exchange=exchange,
                captured_at_utc=str(ts) + "Z",
                spot_price=round(spot, 2),
                perp_mark_price=round(perp_mark, 2),
                perp_index_price=round(spot, 2),
                realized_funding_rate=round(funding, 8),
                funding_interval_hours=funding_interval_hours,
                predicted_funding_rate=None,
                taker_fee_bps=5.0,
                maintenance_margin_rate=0.005,
                borrow_available=True,
                borrow_rate_annual=0.02,
                data_source="synthetic",
                staleness_seconds=0.0,
                source_name="synthetic_funding_snapshots",
            )
        )
    return snapshots


def write_snapshots_json(path: str | Path, snapshots: list[CarrySnapshot]) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"snapshots": [s.to_dict() for s in snapshots]}, indent=2, default=str),
        encoding="utf-8",
    )
    return p


def load_real_adapter(config: dict[str, Any]) -> CarryDataAdapter:
    """Construct the real read-only adapter (lazy import; never trades).

    Not exercised in tests. See docs/CASH_AND_CARRY_PREREGISTRATION.md for the
    exact import commands. Raises if the required extra is not installed.
    """
    from quant_trade.carry.real_adapter import CcxtReadOnlyCarryAdapter

    return CcxtReadOnlyCarryAdapter(config)
