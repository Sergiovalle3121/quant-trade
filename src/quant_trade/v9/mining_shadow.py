"""A shadow collector that survives restarts and cannot fake its own clock.

Shadow mode is the mining route's paper trading: record what the market would
have charged, what a frozen bidding policy would have bid, and — later, when a
pool adapter is attached — what that bid would have received. It buys nothing.

The design problem is that a collector is trivially forgeable. Two of the
three thresholds that gate promotion are "how long has this been running" and
"how many observations", and both are one loop away from being invented. So:

* **Elapsed days come from persisted wall-clock stamps**, written to disk at
  capture time and compared across restarts. Replaying a thousand snapshots in
  one second advances the snapshot count and not the clock, and the journal
  records which mode produced each one.
* **The journal is hash-chained.** Every record carries the digest of its
  predecessor, so a deleted or edited snapshot breaks the chain rather than
  vanishing quietly.
* **Gaps are recorded, not smoothed.** A collector that was down for six hours
  did not observe six hours; the gap is a first-class entry with its duration,
  and the observed-days figure excludes it.
* **The bidding policy is frozen at start.** Its hash goes into the header,
  and changing it mid-window resets the window — otherwise the policy gets
  quietly tuned against the very data that is supposed to test it.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from quant_trade.evidence.canonical_json import (
    atomic_write_json,
    canonical_dumps,
    load_json,
    sha256_of_text,
)
from quant_trade.v9.mining_evidence import (
    STATUS_CANDIDATE,
    STATUS_COLLECTING,
    STATUS_MARKET_ONLY,
)

JOURNAL_FILENAME = "shadow_journal.jsonl"
CHECKPOINT_FILENAME = "shadow_checkpoint.json"
LEASE_FILENAME = "shadow.lease"

#: Promotion thresholds. Both must be met, and neither substitutes for the
#: other: a dense hour is not a fortnight, and a fortnight of two snapshots is
#: not a sample.
MIN_SHADOW_DAYS = 14.0
MIN_SHADOW_SNAPSHOTS = 2_000

#: Beyond this, the collector was down rather than slow, and the interval is
#: recorded as a gap instead of counting as observation.
GAP_THRESHOLD_SECONDS = 1_800.0

#: A heartbeat older than this means the collector is not running now,
#: whatever its history says.
HEARTBEAT_STALE_SECONDS = 900.0

CLOCK_SYSTEM = "system"
CLOCK_INJECTED_TEST = "injected_test"

RECORD_HEADER = "header"
RECORD_SNAPSHOT = "snapshot"
RECORD_GAP = "gap"
RECORD_HEARTBEAT = "heartbeat"


class ShadowError(RuntimeError):
    """The collector cannot continue without losing or inventing evidence."""


@dataclass(frozen=True)
class BiddingPolicy:
    """What the shadow would have bid. Frozen for the whole window."""

    name: str
    bid_percentile: float
    max_price_btc: float
    speed_limit: float
    amount_btc: float
    duration_hours: float

    def digest(self) -> str:
        return sha256_of_text(canonical_dumps(asdict(self)))

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["policy_sha256"] = self.digest()
        return payload


@dataclass(frozen=True)
class MarketSnapshot:
    """One observation of the marketplace, as bytes plus what they meant."""

    captured_at_ms: int
    algorithm: str
    market: str
    best_price_btc: float
    orderbook_depth: int
    raw_sha256: str
    evidence_class: str
    source_url: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ShadowStats:
    snapshots: int = 0
    gaps: int = 0
    gap_seconds: float = 0.0
    observed_seconds: float = 0.0
    first_captured_at_ms: int | None = None
    last_captured_at_ms: int | None = None
    would_have_bid: int = 0
    would_have_filled: int = 0

    @property
    def observed_days(self) -> float:
        return self.observed_seconds / 86_400.0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["observed_days"] = self.observed_days
        return payload


class ShadowCollector:
    """A restart-safe, hash-chained recorder of what the market was doing.

    It reads and writes; it never transacts. There is no order, deposit or
    withdrawal method here, and the module imports no HTTP client — the caller
    supplies snapshots it fetched read-only.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        clock: Callable[[], float] | None = None,
        lease_ttl_seconds: float = 300.0,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._clock = clock or time.time
        self.clock_source = CLOCK_SYSTEM if clock is None else CLOCK_INJECTED_TEST
        self.lease_ttl = lease_ttl_seconds
        self.lease_token = f"{os.getpid()}-{id(self):x}"
        self.policy: BiddingPolicy | None = None
        self.stats = ShadowStats()
        self.sequence = 0
        self.last_digest = ""
        self.last_wall_clock: float | None = None
        self.status = STATUS_MARKET_ONLY
        self.problems: list[str] = []

    # --- paths ------------------------------------------------------------

    @property
    def journal_path(self) -> Path:
        return self.root / JOURNAL_FILENAME

    @property
    def checkpoint_path(self) -> Path:
        return self.root / CHECKPOINT_FILENAME

    @property
    def lease_path(self) -> Path:
        return self.root / LEASE_FILENAME

    # --- lease ------------------------------------------------------------

    def _acquire_lease(self) -> None:
        now = self._clock()
        if self.lease_path.exists():
            try:
                existing = json.loads(self.lease_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                existing = {}
            expires = float(existing.get("expires_at", 0.0))
            if expires > now and str(existing.get("token", "")) != self.lease_token:
                raise ShadowError(
                    f"another collector holds the shadow lease until {expires}; "
                    "two writers would interleave the journal and break the chain"
                )
        atomic_write_json(
            self.lease_path,
            {
                "token": self.lease_token,
                "pid": os.getpid(),
                "acquired_at": now,
                "expires_at": now + self.lease_ttl,
            },
        )

    def release(self) -> None:
        if self.lease_path.exists():
            self.lease_path.unlink()

    # --- journal ----------------------------------------------------------

    def _append(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Append one chained record. The chain is the tamper evidence."""
        self.sequence += 1
        record = {
            "sequence": self.sequence,
            "kind": kind,
            "wall_clock": self._clock(),
            "clock_source": self.clock_source,
            "previous_sha256": self.last_digest,
            "payload": payload,
        }
        record["record_sha256"] = sha256_of_text(canonical_dumps(record))
        with self.journal_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self.last_digest = str(record["record_sha256"])
        return record

    def _read_journal(self) -> list[dict[str, Any]]:
        """Read the journal, tolerating a torn final line from a crash."""
        if not self.journal_path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in self.journal_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                # Only the last line may be torn: a crash mid-write truncates
                # the tail. A torn line anywhere else is corruption.
                self.problems.append("discarded a torn journal line at the tail")
                break
            if isinstance(payload, dict):
                records.append(payload)
        return records

    def verify_chain(self) -> tuple[bool, list[str]]:
        """Recompute every digest. A break names the record that broke it."""
        problems: list[str] = []
        previous = ""
        for record in self._read_journal():
            stated = str(record.get("record_sha256", ""))
            body = {k: v for k, v in record.items() if k != "record_sha256"}
            recomputed = sha256_of_text(canonical_dumps(body))
            if stated != recomputed:
                problems.append(
                    f"record {record.get('sequence')} does not match its own digest: "
                    "it was edited after it was written"
                )
            if str(record.get("previous_sha256", "")) != previous:
                problems.append(
                    f"record {record.get('sequence')} does not follow its predecessor: "
                    "a record was removed or reordered"
                )
            previous = stated
        return (not problems), problems

    # --- lifecycle --------------------------------------------------------

    def start(self, policy: BiddingPolicy) -> None:
        """Begin a window. A different policy starts a new window, not a longer one."""
        self._acquire_lease()
        if self.checkpoint_path.exists():
            checkpoint = load_json(self.checkpoint_path)
            if isinstance(checkpoint, dict):
                existing = str(checkpoint.get("policy_sha256", ""))
                if existing and existing != policy.digest():
                    raise ShadowError(
                        "the bidding policy changed mid-window; the observation "
                        "window restarts rather than counting observations made "
                        "under a different policy"
                    )
        self.policy = policy
        records = self._read_journal()
        if records:
            self.resume()
            return
        self._append(RECORD_HEADER, {"policy": policy.to_dict(), "thresholds": self.thresholds()})
        self._checkpoint()

    def resume(self) -> None:
        """Rebuild state from the journal, which is the authority."""
        self._acquire_lease()
        records = self._read_journal()
        if not records:
            raise ShadowError("no journal to resume from")
        self.stats = ShadowStats()
        self.sequence = 0
        self.last_digest = ""
        self.last_wall_clock = None
        for record in records:
            self.sequence = max(self.sequence, int(record.get("sequence", 0)))
            self.last_digest = str(record.get("record_sha256", ""))
            kind = str(record.get("kind", ""))
            payload = record.get("payload") or {}
            if kind == RECORD_HEADER:
                policy = (payload or {}).get("policy") or {}
                if policy and self.policy is None:
                    self.policy = BiddingPolicy(
                        name=str(policy.get("name", "")),
                        bid_percentile=float(policy.get("bid_percentile", 0.0)),
                        max_price_btc=float(policy.get("max_price_btc", 0.0)),
                        speed_limit=float(policy.get("speed_limit", 0.0)),
                        amount_btc=float(policy.get("amount_btc", 0.0)),
                        duration_hours=float(policy.get("duration_hours", 0.0)),
                    )
            elif kind == RECORD_SNAPSHOT:
                self._absorb_snapshot(record, payload)
            elif kind == RECORD_GAP:
                self.stats.gaps += 1
                self.stats.gap_seconds += float(payload.get("gap_seconds", 0.0))
        self._checkpoint()

    def _absorb_snapshot(self, record: dict[str, Any], payload: dict[str, Any]) -> None:
        wall = float(record.get("wall_clock", 0.0))
        if self.last_wall_clock is not None:
            delta = wall - self.last_wall_clock
            if 0 < delta <= GAP_THRESHOLD_SECONDS:
                self.stats.observed_seconds += delta
        self.last_wall_clock = wall
        self.stats.snapshots += 1
        captured = int(payload.get("captured_at_ms", 0))
        if self.stats.first_captured_at_ms is None:
            self.stats.first_captured_at_ms = captured
        self.stats.last_captured_at_ms = captured
        if payload.get("would_have_bid"):
            self.stats.would_have_bid += 1
        if payload.get("would_have_filled"):
            self.stats.would_have_filled += 1

    def capture(
        self, snapshot: MarketSnapshot, *, orderbook_prices_btc: list[float] | None = None
    ) -> dict[str, Any]:
        """Record one observation and what the frozen policy would have done.

        Real elapsed time between captures is what accumulates; a replay that
        emits a thousand snapshots in a second adds a thousand to the count and
        nothing to the clock, which is the whole point of separating them.
        """
        if self.policy is None:
            raise ShadowError("start(policy) before capturing: the policy must be frozen first")

        now = self._clock()
        if self.last_wall_clock is not None:
            delta = now - self.last_wall_clock
            if delta > GAP_THRESHOLD_SECONDS:
                self._append(
                    RECORD_GAP,
                    {
                        "gap_seconds": delta,
                        "reason": (
                            "no capture for longer than the gap threshold; the "
                            "collector was down and did not observe this interval"
                        ),
                    },
                )
                self.stats.gaps += 1
                self.stats.gap_seconds += delta

        would_bid, would_fill, bid_price = self._evaluate_policy(
            snapshot, orderbook_prices_btc or []
        )
        payload = snapshot.to_dict()
        payload.update(
            {
                "would_have_bid": would_bid,
                "would_have_filled": would_fill,
                "policy_bid_price_btc": bid_price,
                "purchased": False,
            }
        )
        record = self._append(RECORD_SNAPSHOT, payload)
        self._absorb_snapshot(record, payload)
        self._checkpoint()
        return record

    def _evaluate_policy(
        self, snapshot: MarketSnapshot, orderbook_prices_btc: list[float]
    ) -> tuple[bool, bool, float]:
        """What the frozen policy would have bid, and whether it would fill."""
        from quant_trade.v9.mining_units import estimate_delivery

        assert self.policy is not None
        book = sorted(orderbook_prices_btc or [snapshot.best_price_btc], reverse=True)
        index = min(
            len(book) - 1,
            max(0, int(round((1.0 - self.policy.bid_percentile) * (len(book) - 1)))),
        )
        bid = book[index]
        if bid > self.policy.max_price_btc:
            return False, False, bid
        delivery = estimate_delivery(bid, book)
        return True, delivery.expected_fill_ratio > 0.0, bid

    def heartbeat(self) -> dict[str, Any]:
        """Prove the collector is alive now, separately from its history."""
        return self._append(RECORD_HEARTBEAT, {"alive": True})

    def _checkpoint(self) -> None:
        atomic_write_json(self.checkpoint_path, self._checkpoint_payload())

    def _checkpoint_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "sequence": self.sequence,
            "last_digest": self.last_digest,
            "policy_sha256": self.policy.digest() if self.policy else "",
            "clock_source": self.clock_source,
            "stats": self.stats.to_dict(),
            "last_wall_clock": self.last_wall_clock,
        }

    # --- reporting --------------------------------------------------------

    def thresholds(self) -> dict[str, Any]:
        return {
            "min_shadow_days": MIN_SHADOW_DAYS,
            "min_shadow_snapshots": MIN_SHADOW_SNAPSHOTS,
            "gap_threshold_seconds": GAP_THRESHOLD_SECONDS,
        }

    def is_alive(self) -> bool:
        if self.last_wall_clock is None:
            return False
        return (self._clock() - self.last_wall_clock) <= HEARTBEAT_STALE_SECONDS

    def report(self, *, pool_evidence_present: bool = False) -> dict[str, Any]:
        """Where the window stands, and what still blocks promotion."""
        chain_ok, chain_problems = self.verify_chain()
        blocking: list[str] = list(self.problems)
        blocking.extend(chain_problems)

        if not pool_evidence_present:
            status = STATUS_MARKET_ONLY
            blocking.append(
                "no pool payout evidence attached: delivery and payment are "
                "unobserved, so the route is capped at market-only"
            )
        else:
            status = STATUS_COLLECTING
            if self.stats.observed_days < MIN_SHADOW_DAYS:
                blocking.append(
                    f"{self.stats.observed_days:.3f} real days observed of the "
                    f"{MIN_SHADOW_DAYS:.0f} required"
                )
            if self.stats.snapshots < MIN_SHADOW_SNAPSHOTS:
                blocking.append(
                    f"{self.stats.snapshots} snapshots of the {MIN_SHADOW_SNAPSHOTS} required"
                )
            if self.clock_source != CLOCK_SYSTEM:
                blocking.append(
                    "the clock was injected for testing; this window can be "
                    "reported but can never support a promotion"
                )
            if not chain_ok:
                blocking.append("the journal chain is broken")
            if not blocking:
                status = STATUS_CANDIDATE

        self.status = status
        return {
            "artifact": "MINING_SHADOW_JOURNAL",
            "schema_version": 1,
            "status": status,
            "clock_source": self.clock_source,
            "chain_verified": chain_ok,
            "alive": self.is_alive(),
            "policy": self.policy.to_dict() if self.policy else None,
            "thresholds": self.thresholds(),
            "stats": self.stats.to_dict(),
            "blocking_reasons": blocking,
            "orders_placed": 0,
            "btc_spent": 0.0,
            "purchase_authorized": False,
            "note": (
                "Elapsed days accumulate from persisted wall-clock stamps, so "
                "replaying history advances the snapshot count and not the window."
            ),
        }


__all__ = [
    "CLOCK_INJECTED_TEST",
    "CLOCK_SYSTEM",
    "GAP_THRESHOLD_SECONDS",
    "HEARTBEAT_STALE_SECONDS",
    "MIN_SHADOW_DAYS",
    "MIN_SHADOW_SNAPSHOTS",
    "BiddingPolicy",
    "MarketSnapshot",
    "ShadowCollector",
    "ShadowError",
    "ShadowStats",
]
