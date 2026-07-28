"""Turn a backfilled evidence directory into a research-ready carry panel.

The backfill stores five normalized series; research needs one synchronized,
point-in-time table. This module is the join, and it reuses V7's
:func:`quant_trade.carry.panel.build_carry_panel` rather than reimplementing
the semantics that were already argued over there: a row exists only where all
four price series have a bar (nothing is forward-filled), funding accrues only
at exact settlement instants, and the spot close is labelled a proxy for a
tradeable quote rather than passed off as an observed spread.

The panel is rebuilt from the ``series/*.jsonl`` files, which are themselves
derived from archived raw pages — so ``evidence verify`` can reconstruct this
table from the raw bytes alone and byte-compare the result.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from quant_trade.carry.panel import PanelAudit, build_carry_panel, write_panel


@dataclass
class PanelBuildResult:
    status: str  # "OK" | "NO_PANEL"
    venue: str
    symbol: str
    panel_dir: str
    rows: int = 0
    settlements: int = 0
    audit: dict[str, Any] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import asdict

        return asdict(self)


def _read_series(directory: Path, kind: str) -> list[dict[str, Any]]:
    path = directory / "series" / f"{kind}.jsonl"
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def build_panel_from_evidence(
    evidence_dir: str | Path,
    *,
    venue: str,
    symbol: str,
    interval_minutes: int = 60,
    since_ms: int | None = None,
    until_ms: int | None = None,
    provenance: str = "real",
    panel_dir: str | Path | None = None,
) -> PanelBuildResult:
    """Join the backfilled series into a panel and write it with its audit."""
    root = Path(evidence_dir)
    out = Path(panel_dir) if panel_dir is not None else root / "panel"
    result = PanelBuildResult(status="OK", venue=venue, symbol=symbol.upper(), panel_dir=str(out))
    series = {kind: _read_series(root, kind) for kind in ("spot", "perp", "mark", "index")}
    settlements_raw = _read_series(root, "funding")
    missing = [k for k, rows in series.items() if not rows]
    if missing:
        result.status = "NO_PANEL"
        result.problems.append(f"missing series: {sorted(missing)}")
        return result

    # Collapse repeated settlement stamps before the panel builder, which
    # (correctly) refuses duplicates outright: identical repeats are a normal
    # consequence of overlapping pages, contradictions are not.
    by_time: dict[int, float] = {}
    for row in settlements_raw:
        stamp = int(row["settled_at_ms"])
        rate = float(row["rate"])
        previous = by_time.get(stamp)
        if previous is not None and previous != rate:
            result.status = "NO_PANEL"
            result.problems.append(
                f"conflicting funding rates at settlement {stamp}: {previous} vs {rate}"
            )
            return result
        by_time[stamp] = rate
    settlements = [
        {"settled_at_ms": stamp, "rate": rate} for stamp, rate in sorted(by_time.items())
    ]

    rows, audit = build_carry_panel(
        venue=venue,
        symbol=symbol,
        spot=series["spot"],
        perp=series["perp"],
        mark=series["mark"],
        index=series["index"],
        settlements=settlements,
        interval_minutes=interval_minutes,
        requested_since_ms=since_ms,
        requested_until_ms=until_ms,
    )
    audit.provenance = provenance
    if not rows:
        result.status = "NO_PANEL"
        result.problems.extend(audit.problems)
        result.audit = audit.to_dict()
        return result

    write_panel(
        out,
        rows,
        audit,
        build_context={
            "venue": venue,
            "symbol": symbol.upper(),
            "interval_minutes": interval_minutes,
            "requested_since_ms": since_ms,
            "requested_until_ms": until_ms,
            "builder": "v8.panel_builder",
        },
    )
    result.rows = len(rows)
    result.settlements = len(settlements)
    result.audit = audit.to_dict()
    result.problems = list(audit.problems)
    return result


__all__ = ["PanelAudit", "PanelBuildResult", "build_panel_from_evidence"]
