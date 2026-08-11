"""External death list: CoinPaprika's inactive-coin roster.

The universe collector can say when a coin stopped appearing in snapshots. It
cannot say whether the coin died or the source blinked, and that difference is
the whole survivorship question. This module fetches an *independent* opinion —
CoinPaprika's ``is_active`` flag over its full coin roster — so a disappearance
can be corroborated instead of assumed.

Deliberately narrow. It fetches one endpoint, archives the raw bytes
content-addressed with an ingestion receipt, and normalizes to two symbol sets.
It draws no conclusions: `quant_trade.data.quality.universe` does the
cross-check and is explicit that symbol matching is a heuristic (coin ids do
not map across sources).

Absent list => the validator reports NOT_MEASURED. A missing death list is
never read as "no deaths"; that inversion is exactly how a survivorship-poisoned
panel passes for clean.

pandas-free, like the collector, so acquisition runs anywhere.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from quant_trade.carry.backfill import fetch_public_bytes
from quant_trade.evidence.canonical_json import (
    atomic_write_json,
    canonical_dumps,
    load_json,
    sha256_of_bytes,
    sha256_of_text,
)
from quant_trade.evidence.receipts import (
    IngestionReceipt,
    append_receipt,
    normalized_rows_sha256,
    receipt_relative_path,
)

SCHEMA_VERSION = 1

#: Frozen fetch policy; its hash is stored with the result so a list fetched
#: under different rules cannot be mistaken for this one.
DEATHLIST_POLICY: dict[str, Any] = {
    "source": "coinpaprika",
    "endpoint": "https://api.coinpaprika.com/v1/coins",
    "identity_field": "id",
    "activity_field": "is_active",
    "normalized_output": ["inactive_symbols", "active_symbols"],
    "matching_caveat": (
        "symbols are NOT stable identifiers across sources; downstream use is a "
        "declared heuristic, never an identity join"
    ),
}

DEATHLIST_POLICY_SHA256 = sha256_of_text(canonical_dumps(DEATHLIST_POLICY))

DEATHLIST_FILENAME = "deathlist.json"


@dataclass
class DeathListResult:
    status: str  # "OK" | "NOT_RUN_NETWORK_BLOCKED" | "NOT_RUN_PARSE_REJECTED"
    out_dir: str
    total_coins: int = 0
    inactive_coins: int = 0
    active_coins: int = 0
    #: Distinct tickers, NOT a coin count - many coins share a ticker.
    distinct_inactive_symbols: int = 0
    distinct_active_symbols: int = 0
    ambiguous_symbols: int = 0
    raw_sha256: str = ""
    captured_at_utc: str = ""
    error: str = ""
    policy_sha256: str = DEATHLIST_POLICY_SHA256
    provenance: str = "real"
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RosterCounts:
    """Coin-level counts, kept separate from symbol-level ones on purpose.

    Many coins share a ticker, so ``inactive_coins`` and the size of the
    inactive *symbol* set are different numbers. Reporting one as the other
    would overstate or understate the death list by thousands.
    """

    total_coins: int = 0
    inactive_coins: int = 0
    active_coins: int = 0
    unknown_flag_coins: int = 0
    missing_symbol_coins: int = 0


def parse_coin_roster(raw: bytes) -> tuple[list[str], list[str], RosterCounts, list[str]]:
    """Split a CoinPaprika coin roster into inactive/active symbol sets.

    Returns ``(inactive_symbols, active_symbols, counts, warnings)``. A coin
    whose ``is_active`` is absent is neither: an unknown flag is recorded as a
    warning and dropped from both sets, because guessing it either way
    manufactures evidence about exactly the question being asked.
    """
    payload = json.loads(raw)
    if not isinstance(payload, list):
        raise ValueError("coin roster: payload is not a list")
    if not payload:
        raise ValueError("coin roster: payload is empty")
    inactive: set[str] = set()
    active: set[str] = set()
    counts = RosterCounts(total_coins=len(payload))
    for entry in payload:
        if not isinstance(entry, dict):
            raise ValueError("coin roster: entry is not an object")
        flag = entry.get("is_active")
        if flag is True:
            counts.active_coins += 1
        elif flag is False:
            counts.inactive_coins += 1
        else:
            counts.unknown_flag_coins += 1
            continue
        symbol = str(entry.get("symbol") or "").strip().upper()
        if not symbol:
            counts.missing_symbol_coins += 1
            continue
        (active if flag else inactive).add(symbol)
    warnings: list[str] = []
    if counts.unknown_flag_coins:
        warnings.append(
            f"{counts.unknown_flag_coins} coin(s) carry no boolean is_active "
            "flag and were excluded from both sets rather than guessed"
        )
    if counts.missing_symbol_coins:
        warnings.append(f"{counts.missing_symbol_coins} coin(s) carry no symbol")
    return sorted(inactive), sorted(active), counts, warnings


def collect_death_list(
    out_dir: str | Path,
    *,
    fetcher: Callable[[str], bytes] | None = None,
    clock: Callable[[], float] | None = None,
    timeout_seconds: float = 60.0,
) -> DeathListResult:
    """Fetch, archive and normalize the external inactive-coin list."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    active_clock = clock if clock is not None else time.time
    captured = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(active_clock()))
    is_fixture = fetcher is not None
    active_fetch = (
        fetcher
        if fetcher is not None
        else (lambda url: fetch_public_bytes(url, timeout_seconds=timeout_seconds))
    )
    result = DeathListResult(
        status="OK",
        out_dir=str(out),
        captured_at_utc=captured,
        provenance="test_only" if is_fixture else "real",
    )

    url = str(DEATHLIST_POLICY["endpoint"])
    try:
        raw = active_fetch(url)
    except Exception as exc:  # noqa: BLE001 - the verbatim error IS the evidence
        result.status = "NOT_RUN_NETWORK_BLOCKED"
        result.error = f"NOT_RUN_NETWORK_BLOCKED: {type(exc).__name__}: {exc}"
        return result

    try:
        inactive, active, counts, warnings = parse_coin_roster(raw)
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        result.status = "NOT_RUN_PARSE_REJECTED"
        result.error = f"NOT_RUN_PARSE_REJECTED: {type(exc).__name__}: {exc}"
        return result

    sha = sha256_of_bytes(raw)
    raw_dir = out / "raw"
    raw_dir.mkdir(exist_ok=True)
    raw_file = raw_dir / f"{sha}.json"
    if not raw_file.exists():
        raw_file.write_bytes(raw)
    rows = [{"symbol": s, "is_active": False} for s in inactive]
    append_receipt(
        out / "receipts.jsonl",
        IngestionReceipt(
            provider_or_venue="coinpaprika",
            endpoint=url,
            request_parameters={},
            http_status=200,
            captured_at_utc=captured,
            adapter_name="data.deathlist.coinpaprika_roster",
            adapter_version=str(SCHEMA_VERSION),
            raw_path=receipt_relative_path(raw_file, out / "receipts.jsonl"),
            raw_sha256=sha,
            normalized_rows_sha256=normalized_rows_sha256(rows),
            source_kind="fixture" if is_fixture else "live",
        ),
    )

    result.raw_sha256 = sha
    result.total_coins = counts.total_coins
    result.inactive_coins = counts.inactive_coins
    result.active_coins = counts.active_coins
    result.distinct_inactive_symbols = len(inactive)
    result.distinct_active_symbols = len(active)
    result.warnings = warnings

    # A symbol appearing in BOTH sets means two coins share a ticker and only
    # one died. Cross-checking a death by that ticker cannot distinguish them,
    # so the ambiguity is recorded here and the validator's match stays a
    # declared heuristic rather than quietly becoming an identity claim.
    ambiguous = sorted(set(inactive) & set(active))
    result.ambiguous_symbols = len(ambiguous)
    if ambiguous:
        result.warnings.append(
            f"{len(ambiguous)} ticker(s) are carried by both a dead and a live "
            "coin; symbol-level death matching is ambiguous for these"
        )

    atomic_write_json(
        out / DEATHLIST_FILENAME,
        {
            "schema_version": SCHEMA_VERSION,
            "policy_sha256": DEATHLIST_POLICY_SHA256,
            "policy": DEATHLIST_POLICY,
            "captured_at_utc": captured,
            "raw_sha256": sha,
            "source_kind": "fixture" if is_fixture else "live",
            "total_coins": counts.total_coins,
            "inactive_coins": counts.inactive_coins,
            "active_coins": counts.active_coins,
            "unknown_flag_coins": counts.unknown_flag_coins,
            "inactive_symbols": inactive,
            "active_symbols": active,
            "ambiguous_symbols": ambiguous,
            "warnings": result.warnings,
        },
    )
    return result


def load_inactive_symbols(out_dir: str | Path) -> set[str]:
    """Read back the normalized inactive set, refusing a test-only list.

    A fixture-sourced list must never silently corroborate a real dataset's
    deaths, so this raises rather than returning something usable.
    """
    path = Path(out_dir) / DEATHLIST_FILENAME
    if not path.exists():
        raise FileNotFoundError(
            f"no death list at {path}; the death cross-check is NOT_MEASURED "
            "without one and must be reported as such, never as 'no deaths'"
        )
    payload = load_json(path)
    if str(payload.get("source_kind")) != "live":
        raise ValueError(
            f"death list at {path} has source_kind="
            f"{payload.get('source_kind')!r}; a fixture list can never "
            "corroborate real deaths"
        )
    return {str(s).upper() for s in payload.get("inactive_symbols", [])}


__all__ = [
    "DEATHLIST_FILENAME",
    "DEATHLIST_POLICY",
    "DEATHLIST_POLICY_SHA256",
    "DeathListResult",
    "collect_death_list",
    "load_inactive_symbols",
    "parse_coin_roster",
]
