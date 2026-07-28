"""Observability of time, and the handoff when acquisition is blocked.

Two things live here because they are the same problem seen from both ends:
knowing *when* a number became knowable, and knowing *whether* the numbers
exist at all.

**Timing.** Three stamps travel with every bar. ``bar_start_ms`` and
``bar_end_ms`` bound what the bar describes; ``observed_at_ms`` is the first
moment the value could have been read. A close is not observable until the bar
ends, and a bar whose end is within ``safety_lag`` of the venue's server clock
may still be forming — venues publish the in-progress candle on the same
endpoint as the closed ones, and a backtest that keeps it is trading on a
close that had not happened.

Funding is valued at the mark observable **at the settlement instant**. Using
the next hour's close is a small, plausible-looking leak that flatters exactly
the strategies that trade around settlements.

**Handoff.** When egress is blocked, the honest state is ``NOT_MEASURED``, and
the useful output is the exact command an operator runs on their own host plus
a verified import path for what comes back. "We could not download it" without
that command is a status update; with it, it is a next step.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

#: How close to the venue's clock a bar may end and still be trusted as closed.
#: Venues publish the forming candle alongside the closed ones; this is the
#: margin that keeps it out.
DEFAULT_SAFETY_LAG_MS = 60_000


class TimingError(ValueError):
    """A timestamp arrangement that would let the future leak backwards."""


@dataclass(frozen=True)
class StampedBar:
    """A bar that knows when it became knowable."""

    bar_start_ms: int
    bar_end_ms: int
    observed_at_ms: int
    close: float
    high: float
    low: float

    def __post_init__(self) -> None:
        if self.bar_end_ms <= self.bar_start_ms:
            raise TimingError("bar_end_ms must be after bar_start_ms")
        if self.observed_at_ms < self.bar_end_ms:
            raise TimingError(
                f"a bar ending at {self.bar_end_ms} cannot be observed at "
                f"{self.observed_at_ms}: its close has not happened yet"
            )
        if self.low > self.high:
            raise TimingError("low cannot exceed high")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def bar_is_complete(
    bar_end_ms: int, *, server_time_ms: int, safety_lag_ms: int = DEFAULT_SAFETY_LAG_MS
) -> bool:
    """Has this bar definitely closed, allowing for publication lag?"""
    return bar_end_ms <= server_time_ms - safety_lag_ms


@dataclass
class BarFilterResult:
    kept: list[StampedBar] = field(default_factory=list)
    discarded: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kept": len(self.kept),
            "discarded": len(self.discarded),
            "discarded_detail": list(self.discarded[:20]),
            "rule": (
                "a bar is kept only when bar_end_ms <= server_time - safety_lag; "
                "the venue publishes the forming candle on the same endpoint"
            ),
        }


def discard_incomplete_bars(
    bars: Sequence[StampedBar],
    *,
    server_time_ms: int,
    safety_lag_ms: int = DEFAULT_SAFETY_LAG_MS,
) -> BarFilterResult:
    """Drop bars that may still be forming, and say which and why."""
    result = BarFilterResult()
    for bar in bars:
        if bar_is_complete(
            bar.bar_end_ms, server_time_ms=server_time_ms, safety_lag_ms=safety_lag_ms
        ):
            result.kept.append(bar)
        else:
            result.discarded.append(
                {
                    "bar_start_ms": bar.bar_start_ms,
                    "bar_end_ms": bar.bar_end_ms,
                    "server_time_ms": server_time_ms,
                    "safety_lag_ms": safety_lag_ms,
                    "reason": (
                        "bar may still be forming: it ends within the safety lag "
                        "of the venue's own clock"
                    ),
                }
            )
    return result


@dataclass
class ValuedSettlement:
    settled_at_ms: int
    rate: float
    mark: float
    mark_bar_end_ms: int
    mark_observed_at_ms: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def value_settlements_at_observation(
    settlements: Sequence[tuple[int, float]],
    marks: Sequence[StampedBar],
) -> tuple[list[ValuedSettlement], list[str]]:
    """Price each settlement with the mark observable when it settled.

    The mark used is the most recent bar whose close was already observable at
    the settlement instant. Reaching forward to the bar that *contains* the
    settlement — or worse, the next hour's close — is look-ahead: at the moment
    funding settled, that number did not exist.
    """
    ordered = sorted(marks, key=lambda b: b.observed_at_ms)
    observed = [b.observed_at_ms for b in ordered]
    valued: list[ValuedSettlement] = []
    problems: list[str] = []
    for settled_at_ms, rate in sorted(settlements):
        index = bisect_right(observed, settled_at_ms) - 1
        if index < 0:
            problems.append(
                f"settlement at {settled_at_ms} precedes every observable mark; "
                "it cannot be valued without reaching forward"
            )
            continue
        bar = ordered[index]
        valued.append(
            ValuedSettlement(
                settled_at_ms=settled_at_ms,
                rate=rate,
                mark=bar.close,
                mark_bar_end_ms=bar.bar_end_ms,
                mark_observed_at_ms=bar.observed_at_ms,
            )
        )
    return valued, problems


# --- acquisition handoff ------------------------------------------------------------


ACQUISITION_NOT_MEASURED = "NOT_MEASURED"
ACQUISITION_BLOCKED = "BLOCKED_EVIDENCE"
ACQUISITION_AVAILABLE = "EVIDENCE_AVAILABLE"


@dataclass
class AcquisitionStatus:
    """Where the dataset stands, and what the operator should run next."""

    state: str
    venues: dict[str, Any] = field(default_factory=dict)
    blocked_hosts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    operator_commands: list[str] = field(default_factory=list)
    import_command: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["artifact"] = "DATA_AND_COST_EVIDENCE_INDEX"
        payload["schema_version"] = 1
        payload["measured"] = self.state == ACQUISITION_AVAILABLE
        return payload


def operator_runbook(
    *,
    since_utc: str,
    until_utc: str,
    evidence_root: str = "data/v9_evidence",
    pack_dir: str = "data/v9_packs",
) -> list[str]:
    """The exact commands to run on a host with egress. No secrets involved."""
    return [
        "# 1. Confirm the venues are reachable from this host.",
        "quant-trade v8 probe-network",
        "",
        "# 2. Capture 730+ days of public market data per venue (resumable).",
        f"quant-trade v8 evidence-backfill --venue bybit --symbol BTC "
        f"--since {since_utc} --until {until_utc} --evidence-root {evidence_root}",
        f"quant-trade v8 evidence-backfill --venue okx --symbol BTC "
        f"--since {since_utc} --until {until_utc} --evidence-root {evidence_root}",
        "",
        "# 3. Confirm the capture meets the pre-registered sufficiency floor.",
        f"quant-trade v8 evidence-validate --venue bybit --evidence-root {evidence_root}",
        f"quant-trade v8 evidence-validate --venue okx --evidence-root {evidence_root}",
        "",
        "# 4. Capture your account's own fee schedule (read-only key; NO withdraw).",
        "#    Run the venue call yourself and keep only the response bytes.",
        "quant-trade v9 cost-import --venue bybit --raw <bybit-fee-rate.json> \\",
        "    --effective-from <iso> --expires-at <iso>",
        "quant-trade v9 cost-import --venue okx --raw <okx-trade-fee.json> \\",
        "    --effective-from <iso> --expires-at <iso>",
        "",
        "# 5. Build a content-addressed pack and hand it back.",
        f"quant-trade v8 evidence-pack --evidence-root {evidence_root} --out-dir {pack_dir}",
    ]


def evaluate_acquisition(
    *,
    evidence_root: str | Path,
    venues: tuple[str, ...] = ("bybit", "okx"),
    since_utc: str,
    until_utc: str,
    min_days: float,
    min_settlements: int,
) -> AcquisitionStatus:
    """Report what evidence exists, and hand back a runbook when it does not."""
    from quant_trade.evidence.canonical_json import load_json
    from quant_trade.v8.backfill import evidence_dir_for
    from quant_trade.v8.validation import sufficiency_report, validate_evidence_dir

    status = AcquisitionStatus(state=ACQUISITION_NOT_MEASURED)
    sufficient_venues = 0
    for venue in venues:
        directory = evidence_dir_for(evidence_root, venue, "BTC")
        entry: dict[str, Any] = {"venue": venue, "directory": str(directory)}
        if not directory.exists():
            entry["present"] = False
            entry["reason"] = "no evidence directory: acquisition never completed"
            status.venues[venue] = entry
            continue
        attempts = directory / "attempts.jsonl"
        if attempts.exists():
            for line in attempts.read_text(encoding="utf-8").splitlines():
                if "403" in line or "tunnel" in line.lower():
                    host = venue
                    if host not in status.blocked_hosts:
                        status.blocked_hosts.append(host)
                    break
        context_path = directory / "backfill_result.json"
        context = load_json(context_path) if context_path.exists() else {}
        context = context if isinstance(context, dict) else {}
        validation = validate_evidence_dir(
            directory,
            since_ms=int(context.get("since_ms", 0) or 0),
            until_ms=int(context.get("until_ms", 0) or 0),
            interval_minutes=int(context.get("interval_minutes", 60) or 60),
            venue=venue,
            symbol="BTC",
        )
        sufficiency = sufficiency_report(
            validation, min_days=min_days, min_settlements=min_settlements
        )
        entry.update(
            {
                "present": True,
                "provenance": validation.provenance,
                "raw_pages": validation.raw_pages,
                "receipts": validation.receipts,
                "sufficiency": sufficiency,
            }
        )
        status.venues[venue] = entry
        if sufficiency["sufficient"]:
            sufficient_venues += 1
        else:
            status.errors.extend(f"{venue}: {s}" for s in sufficiency["shortfalls"])

    if sufficient_venues == len(venues):
        status.state = ACQUISITION_AVAILABLE
    elif status.blocked_hosts:
        status.state = ACQUISITION_BLOCKED
    status.operator_commands = operator_runbook(since_utc=since_utc, until_utc=until_utc)
    status.import_command = (
        "quant-trade v8 evidence-verify --pack <archive.tar.gz> "
        "--manifest <EVIDENCE_PACK_MANIFEST.json> --import-to data/v9_evidence"
    )
    status.notes = [
        "A blocked acquisition is NOT_MEASURED, never a negative result: "
        "nothing about the hypothesis has been tested.",
        "The import path verifies byte-for-byte before extracting, so an "
        "operator-supplied pack is checkable rather than trusted.",
    ]
    return status


__all__ = [
    "ACQUISITION_AVAILABLE",
    "ACQUISITION_BLOCKED",
    "ACQUISITION_NOT_MEASURED",
    "DEFAULT_SAFETY_LAG_MS",
    "AcquisitionStatus",
    "BarFilterResult",
    "StampedBar",
    "TimingError",
    "ValuedSettlement",
    "bar_is_complete",
    "discard_incomplete_bars",
    "evaluate_acquisition",
    "operator_runbook",
    "value_settlements_at_observation",
]
