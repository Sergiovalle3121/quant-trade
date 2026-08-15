"""Causal, selection-only acquisition plan for Binance Spot H2 research.

This module is a deliberately narrow safety boundary.  It discovers venue
symbols only from normalized CoinMarketCap day files inside the frozen
selection interval, records the exact bytes of every day it opened, and then
invokes the venue collector with Binance and the same interval hard-bound.

It never enumerates a current exchange universe and never scans a directory
for "the newest" file.  The only paths it opens are the deterministic
``days/YYYY-MM-DD.jsonl`` paths in the frozen interval.  Consequently a
holdout file copied next to the selection files cannot change the plan.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from quant_trade.data.universe import read_journal, verify_journal_chain
from quant_trade.data.venue_klines import (
    JOURNAL_FILENAME,
    VENUE_BINANCE,
    VENUE_POLICIES,
    VENUE_POLICY_SHA256,
    HttpResponse,
    VenueKlineResult,
    collect_venue_klines,
)
from quant_trade.evidence.canonical_json import (
    atomic_write_text,
    canonical_dumps,
    sha256_of_bytes,
    sha256_of_text,
)

SCHEMA_VERSION = 1

SELECTION_START = date(2017, 8, 17)
SELECTION_END = date(2023, 11, 28)

SYMBOLS_FILENAME = "symbols_selection.txt"
MANIFEST_FILENAME = "selection_manifest.json"
BINDING_FILENAME = "selection_collection_binding.json"

_TICKER_PATTERN = re.compile(r"^[A-Z0-9]{1,20}$")


class CryptoSelectionError(RuntimeError):
    """A selection boundary, provenance, or output-isolation violation."""


@dataclass(frozen=True)
class BinanceH2SelectionSpec:
    """The one allowed acquisition specification.

    Construction itself fails for a changed venue, market, or date.  A caller
    therefore cannot make an object that merely *looks* like this policy while
    pointing at Bybit or at the reserved holdout.
    """

    venue: str = VENUE_BINANCE
    market: str = "spot"
    quote_asset: str = "USDT"
    start_date: date = SELECTION_START
    end_date: date = SELECTION_END
    rank_ceiling: int = 1000
    market_cap_min_usd: float = 10_000_000.0
    market_cap_max_usd: float = 1_000_000_000.0
    stablecoin_field: str = "is_stablecoin"

    def __post_init__(self) -> None:
        expected = (
            VENUE_BINANCE,
            "spot",
            "USDT",
            SELECTION_START,
            SELECTION_END,
            1000,
            10_000_000.0,
            1_000_000_000.0,
            "is_stablecoin",
        )
        observed = (
            self.venue,
            self.market,
            self.quote_asset,
            self.start_date,
            self.end_date,
            self.rank_ceiling,
            self.market_cap_min_usd,
            self.market_cap_max_usd,
            self.stablecoin_field,
        )
        if observed != expected:
            raise CryptoSelectionError(
                "Binance H2 acquisition is frozen to Binance Spot/USDT, "
                "2017-08-17..2023-11-28, rank<=1000 and USD 10M..1B"
            )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["start_date"] = self.start_date.isoformat()
        payload["end_date"] = self.end_date.isoformat()
        return payload


BINANCE_H2_SELECTION_SPEC = BinanceH2SelectionSpec()

SELECTION_POLICY: dict[str, Any] = {
    "schema_version": SCHEMA_VERSION,
    "spec": BINANCE_H2_SELECTION_SPEC.to_dict(),
    "source": "normalized_coinmarketcap_daily_files",
    "source_path_rule": "days/YYYY-MM-DD.jsonl for each frozen selection date only",
    "streaming": True,
    "identity": "CMC:<cmc_id>",
    "eligibility": (
        "first causal row with rank<=1000 and market_cap_usd in [10M,1B]; "
        "an explicit is_stablecoin=true row is ineligible"
    ),
    "ticker_history": (
        "include the ticker on first eligibility and later observed tickers for that "
        "already-eligible cmc_id; never backfill a pre-eligibility ticker"
    ),
    "stablecoin_unknown": "do not infer from a future/current classification",
    "venue_symbol": "<valid uppercase alphanumeric ticker>USDT",
    "output_reuse": (
        "new/empty or exact resume only: immutable intent binding plus a valid "
        "Binance policy/window journal; unbound or orphaned cache bytes are refused"
    ),
}
SELECTION_POLICY_SHA256 = sha256_of_text(canonical_dumps(SELECTION_POLICY))


@dataclass(frozen=True)
class SelectionPlanResult:
    out_dir: str
    manifest_path: str
    symbols_path: str
    manifest_digest: str
    source_days: int
    missing_days: int
    eligible_identities: int
    symbols: int


@dataclass(frozen=True)
class SelectionResearchReadiness:
    """Fail-closed verdict for using a plan to build the H2 causal panel.

    This is deliberately narrower than an experiment or promotion verdict. A
    ready selection plan only permits the next offline data-engineering step;
    it never proves alpha, opens the holdout, or authorizes P&L generation.
    """

    status: str
    plan_digest: str
    blockers: tuple[str, ...]
    expected_source_days: int
    source_days: int | None
    causal_rows_considered: int | None
    stablecoin_field_rows: int | None
    stablecoin_field_missing_rows: int | None
    eligible_identities: int | None
    symbols: int | None

    @property
    def ready(self) -> bool:
        return self.status == "READY_FOR_CAUSAL_PANEL_BUILD" and not self.blockers

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "ready": self.ready,
            "holdout_access_authorized": False,
            "pnl_generation_authorized": False,
            "profitability_evidence": False,
            "real_money_authorized": False,
        }


def _selection_dates() -> list[date]:
    count = (SELECTION_END - SELECTION_START).days
    return [SELECTION_START + timedelta(days=offset) for offset in range(count + 1)]


def _require_new_or_empty(path: Path, *, label: str) -> None:
    if path.exists():
        if not path.is_dir() or path.is_symlink():
            raise CryptoSelectionError(f"{label} must be a real directory: {path}")
        if next(path.iterdir(), None) is not None:
            raise CryptoSelectionError(
                f"{label} is not empty ({path}); existing caches/evidence cannot be mixed"
            )
    else:
        path.mkdir(parents=True)


def _finite_number(value: Any, *, field: str, source: Path, line_number: int) -> float:
    if isinstance(value, bool):
        raise CryptoSelectionError(f"{source}:{line_number}: {field} cannot be boolean")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise CryptoSelectionError(f"{source}:{line_number}: invalid {field}={value!r}") from exc
    if not math.isfinite(number):
        raise CryptoSelectionError(f"{source}:{line_number}: non-finite {field}")
    return number


def _causal_stablecoin_flag(
    row: dict[str, Any], *, source: Path, line_number: int
) -> tuple[bool, bool]:
    field = BINANCE_H2_SELECTION_SPEC.stablecoin_field
    if field not in row:
        return False, False
    value = row[field]
    if type(value) is not bool:
        raise CryptoSelectionError(
            f"{source}:{line_number}: {field} must be a historical boolean when present"
        )
    return value, True


def _valid_venue_ticker(ticker: str) -> tuple[bool, str]:
    if ticker == BINANCE_H2_SELECTION_SPEC.quote_asset:
        return False, "quote_asset_cannot_be_base"
    if not _TICKER_PATTERN.fullmatch(ticker):
        return False, "not_uppercase_alphanumeric_1_to_20"
    return True, ""


def _update_mapping(
    mappings: dict[tuple[int, str], dict[str, Any]],
    *,
    cmc_id: int,
    ticker: str,
    day_iso: str,
    eligible_today: bool,
) -> None:
    key = (cmc_id, ticker)
    mapping = mappings.get(key)
    if mapping is None:
        mapping = {
            "instrument_id": f"CMC:{cmc_id}",
            "cmc_id": cmc_id,
            "ticker": ticker,
            "venue_symbol": f"{ticker}{BINANCE_H2_SELECTION_SPEC.quote_asset}",
            "first_observed_date": day_iso,
            "last_observed_date": day_iso,
            "observations": 0,
            "eligible_observations": 0,
        }
        mappings[key] = mapping
    mapping["last_observed_date"] = day_iso
    mapping["observations"] += 1
    if eligible_today:
        mapping["eligible_observations"] += 1


def _update_rejection(
    rejected: dict[tuple[int, str, str], dict[str, Any]],
    *,
    cmc_id: int,
    ticker: str,
    reason: str,
    day_iso: str,
) -> None:
    key = (cmc_id, ticker, reason)
    record = rejected.get(key)
    if record is None:
        record = {
            "instrument_id": f"CMC:{cmc_id}",
            "ticker": ticker,
            "reason": reason,
            "first_date": day_iso,
            "last_date": day_iso,
            "observations": 0,
        }
        rejected[key] = record
    record["last_date"] = day_iso
    record["observations"] += 1


def build_binance_h2_selection_plan(
    universe_dir: str | Path,
    out_dir: str | Path,
    *,
    spec: BinanceH2SelectionSpec = BINANCE_H2_SELECTION_SPEC,
) -> SelectionPlanResult:
    """Build a canonical selection-only symbol plan from normalized CMC days.

    ``spec`` is accepted so callers can bind the intended policy explicitly,
    but only the module's exact frozen value is valid.  Files outside the
    interval are neither globbed nor opened.  Missing dates are explicit in
    the manifest rather than silently filled from a cache.
    """
    if spec != BINANCE_H2_SELECTION_SPEC:
        raise CryptoSelectionError("only the frozen Binance H2 selection spec is allowed")

    universe = Path(universe_dir)
    output = Path(out_dir)
    _require_new_or_empty(output, label="selection-plan output")

    eligible_ids: set[int] = set()
    first_eligible_date: dict[int, str] = {}
    mappings: dict[tuple[int, str], dict[str, Any]] = {}
    rejected: dict[tuple[int, str, str], dict[str, Any]] = {}
    sources: list[dict[str, Any]] = []
    missing_dates: list[str] = []
    total_rows = 0
    causal_rows_considered = 0
    duplicate_rows = 0
    stablecoin_rows = 0
    stablecoin_field_rows = 0

    for day in _selection_dates():
        day_iso = day.isoformat()
        source = universe / "days" / f"{day_iso}.jsonl"
        if not source.exists():
            missing_dates.append(day_iso)
            continue
        if not source.is_file() or source.is_symlink():
            raise CryptoSelectionError(f"selection source must be a regular file: {source}")

        byte_digest = hashlib.sha256()
        source_rows = 0
        source_duplicates = 0
        seen_ids: set[int] = set()
        with source.open("rb") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                byte_digest.update(raw_line)
                stripped = raw_line.strip()
                if not stripped:
                    continue
                try:
                    parsed = json.loads(stripped.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise CryptoSelectionError(
                        f"{source}:{line_number}: invalid normalized JSON row"
                    ) from exc
                if not isinstance(parsed, dict):
                    raise CryptoSelectionError(
                        f"{source}:{line_number}: normalized row must be an object"
                    )
                row: dict[str, Any] = parsed
                source_rows += 1
                total_rows += 1

                raw_id: Any = row.get("cmc_id")
                if isinstance(raw_id, bool):
                    raise CryptoSelectionError(
                        f"{source}:{line_number}: cmc_id must be a positive integer"
                    )
                try:
                    cmc_id = int(raw_id)
                except (TypeError, ValueError) as exc:
                    raise CryptoSelectionError(
                        f"{source}:{line_number}: cmc_id must be a positive integer"
                    ) from exc
                if cmc_id <= 0 or raw_id != cmc_id:
                    raise CryptoSelectionError(
                        f"{source}:{line_number}: cmc_id must be a positive integer"
                    )
                if cmc_id in seen_ids:
                    source_duplicates += 1
                    duplicate_rows += 1
                    continue
                seen_ids.add(cmc_id)
                causal_rows_considered += 1

                ticker = str(row.get("symbol", "")).strip().upper()
                rank_raw = row.get("cmc_rank")
                rank = (
                    _finite_number(
                        rank_raw,
                        field="cmc_rank",
                        source=source,
                        line_number=line_number,
                    )
                    if rank_raw is not None
                    else None
                )
                market_cap = _finite_number(
                    row.get("market_cap_usd"),
                    field="market_cap_usd",
                    source=source,
                    line_number=line_number,
                )
                is_stablecoin, has_stablecoin_field = _causal_stablecoin_flag(
                    row, source=source, line_number=line_number
                )
                if has_stablecoin_field:
                    stablecoin_field_rows += 1
                if is_stablecoin:
                    stablecoin_rows += 1

                eligible_today = (
                    rank is not None
                    and rank <= spec.rank_ceiling
                    and spec.market_cap_min_usd <= market_cap <= spec.market_cap_max_usd
                    and not is_stablecoin
                )
                was_eligible = cmc_id in eligible_ids
                if eligible_today:
                    eligible_ids.add(cmc_id)
                    first_eligible_date.setdefault(cmc_id, day_iso)

                # A new identity enters only from today's causal eligibility.
                # Once observed eligible, later tickers are retained even after
                # rank exit so a held position can still be marked or exited.
                if not (eligible_today or was_eligible):
                    continue
                valid, reason = _valid_venue_ticker(ticker)
                if not valid:
                    _update_rejection(
                        rejected,
                        cmc_id=cmc_id,
                        ticker=ticker,
                        reason=reason,
                        day_iso=day_iso,
                    )
                    continue
                _update_mapping(
                    mappings,
                    cmc_id=cmc_id,
                    ticker=ticker,
                    day_iso=day_iso,
                    eligible_today=eligible_today,
                )

        sources.append(
            {
                "date": day_iso,
                "relative_path": f"days/{day_iso}.jsonl",
                "sha256": byte_digest.hexdigest(),
                "bytes": source.stat().st_size,
                "rows": source_rows,
                "duplicate_cmc_id_rows_ignored": source_duplicates,
            }
        )

    ordered_mappings = [mappings[key] for key in sorted(mappings)]
    symbols = sorted({str(mapping["venue_symbol"]) for mapping in ordered_mappings})
    symbols_bytes = (("\n".join(symbols) + "\n") if symbols else "").encode("utf-8")

    ids_by_ticker: dict[str, set[int]] = {}
    tickers_by_id: dict[int, set[str]] = {}
    for mapping in ordered_mappings:
        ticker = str(mapping["ticker"])
        cmc_id = int(mapping["cmc_id"])
        ids_by_ticker.setdefault(ticker, set()).add(cmc_id)
        tickers_by_id.setdefault(cmc_id, set()).add(ticker)

    manifest_payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "dataset_kind": "binance_h2_selection_acquisition_plan",
        "status": (
            "READY_FOR_SELECTION_ACQUISITION"
            if stablecoin_field_rows == causal_rows_considered
            else "INSUFFICIENT_EVIDENCE"
        ),
        "blockers": (
            []
            if stablecoin_field_rows == causal_rows_considered
            else [
                {
                    "code": "HISTORICAL_STABLECOIN_CLASSIFICATION_MISSING",
                    "affected_rows": causal_rows_considered - stablecoin_field_rows,
                    "effect": (
                        "rows without a causal is_stablecoin field were not excluded; "
                        "the plan is not a research-ready universe"
                    ),
                }
            ]
        ),
        "profitability_evidence": False,
        "policy": SELECTION_POLICY,
        "policy_sha256": SELECTION_POLICY_SHA256,
        "spec": spec.to_dict(),
        "source_boundary": {
            "first_allowed_date": SELECTION_START.isoformat(),
            "last_allowed_date": SELECTION_END.isoformat(),
            "holdout_or_later_opened": False,
            "source_days": len(sources),
            "missing_dates": missing_dates,
        },
        "sources": sources,
        "discovery": {
            "rows_streamed": total_rows,
            "causal_rows_considered": causal_rows_considered,
            "duplicate_cmc_id_rows_ignored": duplicate_rows,
            "eligible_identities": len(eligible_ids),
            "first_eligible_date_by_instrument": {
                f"CMC:{cmc_id}": first_eligible_date[cmc_id]
                for cmc_id in sorted(first_eligible_date)
            },
            "stablecoin_field_rows": stablecoin_field_rows,
            "stablecoin_true_rows_excluded_from_entry": stablecoin_rows,
            "stablecoin_field_missing_rows": causal_rows_considered - stablecoin_field_rows,
            "instrument_ticker_mappings": ordered_mappings,
            "ticker_reuse": [
                {
                    "ticker": ticker,
                    "instrument_ids": [f"CMC:{cmc_id}" for cmc_id in sorted(ids)],
                }
                for ticker, ids in sorted(ids_by_ticker.items())
                if len(ids) > 1
            ],
            "renamed_instruments": [
                {
                    "instrument_id": f"CMC:{cmc_id}",
                    "tickers": sorted(tickers),
                }
                for cmc_id, tickers in sorted(tickers_by_id.items())
                if len(tickers) > 1
            ],
            "rejected_ticker_observations": [rejected[key] for key in sorted(rejected)],
        },
        "outputs": {
            "symbols_file": SYMBOLS_FILENAME,
            "symbols_file_sha256": sha256_of_bytes(symbols_bytes),
            "symbols_count": len(symbols),
            "symbols_order": "ASCII ascending, unique, one venue symbol per LF line",
        },
    }
    manifest_digest = sha256_of_text(canonical_dumps(manifest_payload))
    manifest = dict(manifest_payload)
    manifest["digest"] = manifest_digest

    atomic_write_text(output / SYMBOLS_FILENAME, symbols_bytes.decode("utf-8"))
    atomic_write_text(output / MANIFEST_FILENAME, canonical_dumps(manifest) + "\n")
    return SelectionPlanResult(
        out_dir=str(output),
        manifest_path=str(output / MANIFEST_FILENAME),
        symbols_path=str(output / SYMBOLS_FILENAME),
        manifest_digest=manifest_digest,
        source_days=len(sources),
        missing_days=len(missing_dates),
        eligible_identities=len(eligible_ids),
        symbols=len(symbols),
    )


def load_binance_h2_selection_plan(plan_dir: str | Path) -> dict[str, Any]:
    """Load and verify canonical manifest and symbol bytes without source rescans."""
    root = Path(plan_dir)
    manifest_path = root / MANIFEST_FILENAME
    try:
        raw = manifest_path.read_bytes()
        parsed = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise CryptoSelectionError(f"cannot load selection manifest: {manifest_path}") from exc
    if not isinstance(parsed, dict):
        raise CryptoSelectionError("selection manifest must be a JSON object")
    digest = parsed.get("digest")
    if not isinstance(digest, str):
        raise CryptoSelectionError("selection manifest has no digest")
    payload = dict(parsed)
    payload.pop("digest", None)
    expected = sha256_of_text(canonical_dumps(payload))
    if digest != expected:
        raise CryptoSelectionError("selection manifest digest mismatch")
    if raw != (canonical_dumps(parsed) + "\n").encode("utf-8"):
        raise CryptoSelectionError("selection manifest bytes are not canonical")
    if parsed.get("policy_sha256") != SELECTION_POLICY_SHA256:
        raise CryptoSelectionError("selection policy digest does not match frozen policy")
    if parsed.get("spec") != BINANCE_H2_SELECTION_SPEC.to_dict():
        raise CryptoSelectionError("selection manifest does not carry the frozen Binance spec")

    outputs = parsed.get("outputs")
    if not isinstance(outputs, dict) or outputs.get("symbols_file") != SYMBOLS_FILENAME:
        raise CryptoSelectionError("selection manifest has an invalid symbols binding")
    symbols_path = root / SYMBOLS_FILENAME
    try:
        symbols_bytes = symbols_path.read_bytes()
    except OSError as exc:
        raise CryptoSelectionError(f"cannot read bound symbols file: {symbols_path}") from exc
    if sha256_of_bytes(symbols_bytes) != outputs.get("symbols_file_sha256"):
        raise CryptoSelectionError("symbols_selection.txt byte hash mismatch")
    symbols = symbols_bytes.decode("utf-8").splitlines()
    if symbols != sorted(set(symbols)) or any(not symbol for symbol in symbols):
        raise CryptoSelectionError("symbols_selection.txt is not canonical sorted/unique text")
    if len(symbols) != outputs.get("symbols_count"):
        raise CryptoSelectionError("symbols count differs from selection manifest")
    return parsed


def _nonnegative_manifest_int(
    container: dict[str, Any],
    key: str,
    *,
    blockers: list[str],
) -> int | None:
    value = container.get(key)
    if type(value) is not int or value < 0:
        blockers.append(f"MALFORMED_{key.upper()}")
        return None
    return value


def evaluate_binance_h2_selection_research_readiness(
    plan_dir: str | Path,
) -> SelectionResearchReadiness:
    """Verify that a plan may feed the next *offline panel-build* step.

    Acquisition can be staged from an incomplete plan, so the plan builder and
    collector intentionally remain usable while evidence is missing. This
    stricter boundary is the one a causal-panel builder must call. It derives
    readiness from the verified manifest contents rather than trusting its
    status label alone.
    """

    plan = load_binance_h2_selection_plan(plan_dir)
    blockers: list[str] = []

    if plan.get("status") != "READY_FOR_SELECTION_ACQUISITION":
        blockers.append("PLAN_STATUS_NOT_READY_FOR_SELECTION_ACQUISITION")
    if plan.get("blockers") != []:
        blockers.append("PLAN_BLOCKERS_PRESENT")
    if plan.get("profitability_evidence") is not False:
        blockers.append("INVALID_PROFITABILITY_EVIDENCE_CLAIM")

    boundary = plan.get("source_boundary")
    if not isinstance(boundary, dict):
        boundary = {}
        blockers.append("MALFORMED_SOURCE_BOUNDARY")
    expected_dates = [day.isoformat() for day in _selection_dates()]
    expected_source_days = len(expected_dates)
    source_days = _nonnegative_manifest_int(boundary, "source_days", blockers=blockers)
    if source_days != expected_source_days:
        blockers.append("SELECTION_SOURCE_DAYS_INCOMPLETE")
    if boundary.get("missing_dates") != []:
        blockers.append("SELECTION_DATES_MISSING")
    if (
        boundary.get("first_allowed_date") != SELECTION_START.isoformat()
        or boundary.get("last_allowed_date") != SELECTION_END.isoformat()
        or boundary.get("holdout_or_later_opened") is not False
    ):
        blockers.append("PROTECTED_HOLDOUT_BOUNDARY_NOT_PROVEN")

    sources = plan.get("sources")
    if not isinstance(sources, list):
        sources = []
        blockers.append("MALFORMED_SOURCES")
    observed_source_dates: list[str] = []
    sources_well_formed = True
    for source in sources:
        if not isinstance(source, dict):
            sources_well_formed = False
            continue
        day_iso = source.get("date")
        relative_path = source.get("relative_path")
        if not isinstance(day_iso, str) or relative_path != f"days/{day_iso}.jsonl":
            sources_well_formed = False
            continue
        observed_source_dates.append(day_iso)
    if not sources_well_formed or observed_source_dates != expected_dates:
        blockers.append("SELECTION_SOURCE_SEQUENCE_INCOMPLETE")

    discovery = plan.get("discovery")
    if not isinstance(discovery, dict):
        discovery = {}
        blockers.append("MALFORMED_DISCOVERY")
    causal_rows = _nonnegative_manifest_int(discovery, "causal_rows_considered", blockers=blockers)
    stablecoin_rows = _nonnegative_manifest_int(
        discovery, "stablecoin_field_rows", blockers=blockers
    )
    stablecoin_missing = _nonnegative_manifest_int(
        discovery, "stablecoin_field_missing_rows", blockers=blockers
    )
    eligible_identities = _nonnegative_manifest_int(
        discovery, "eligible_identities", blockers=blockers
    )
    if causal_rows == 0:
        blockers.append("EMPTY_CAUSAL_UNIVERSE")
    if (
        causal_rows is None
        or stablecoin_rows is None
        or stablecoin_missing is None
        or stablecoin_rows != causal_rows
        or stablecoin_missing != 0
    ):
        blockers.append("HISTORICAL_STABLECOIN_CLASSIFICATION_INCOMPLETE")
    if eligible_identities == 0:
        blockers.append("NO_ELIGIBLE_IDENTITIES")

    outputs = plan.get("outputs")
    if not isinstance(outputs, dict):
        outputs = {}
        blockers.append("MALFORMED_OUTPUTS")
    symbols = _nonnegative_manifest_int(outputs, "symbols_count", blockers=blockers)
    if symbols == 0:
        blockers.append("NO_VENUE_SYMBOLS")

    unique_blockers = tuple(dict.fromkeys(blockers))
    return SelectionResearchReadiness(
        status=("READY_FOR_CAUSAL_PANEL_BUILD" if not unique_blockers else "INSUFFICIENT_EVIDENCE"),
        plan_digest=str(plan["digest"]),
        blockers=unique_blockers,
        expected_source_days=expected_source_days,
        source_days=source_days,
        causal_rows_considered=causal_rows,
        stablecoin_field_rows=stablecoin_rows,
        stablecoin_field_missing_rows=stablecoin_missing,
        eligible_identities=eligible_identities,
        symbols=symbols,
    )


def require_binance_h2_selection_research_ready(
    plan_dir: str | Path,
) -> dict[str, Any]:
    """Return the verified plan or refuse causal-panel construction.

    Passing this one gate does not authorize holdout access or P&L. It only
    proves that selection coverage and the declared historical stablecoin
    field are complete enough to begin the separately governed panel build.
    """

    verdict = evaluate_binance_h2_selection_research_readiness(plan_dir)
    if not verdict.ready:
        raise CryptoSelectionError(
            "Binance H2 selection plan is not research-ready: " + ", ".join(verdict.blockers)
        )
    return load_binance_h2_selection_plan(plan_dir)


def collect_binance_h2_selection_klines(
    plan_dir: str | Path,
    out_dir: str | Path,
    *,
    venue: str = VENUE_BINANCE,
    start_date: date = SELECTION_START,
    end_date: date = SELECTION_END,
    fetcher: Callable[[str], HttpResponse] | None = None,
    clock: Callable[[], float] | None = None,
    sleep_seconds: float = 0.0,
    timeout_seconds: float = 30.0,
    max_symbols_per_run: int | None = None,
) -> VenueKlineResult:
    """Fetch the bound symbols with an immutable Binance selection window.

    The explicit arguments make an accidental caller override observable, but
    every value except the frozen one is refused before a network function is
    invoked.  The venue output must also be new/empty: a prior Bybit cache or a
    differently bounded Binance journal can never be resumed through this
    wrapper.
    """
    if venue != VENUE_BINANCE:
        raise CryptoSelectionError("H2 selection acquisition permits Binance only")
    if start_date != SELECTION_START or end_date != SELECTION_END:
        raise CryptoSelectionError(
            "H2 selection acquisition is hard-bound to 2017-08-17..2023-11-28"
        )
    plan = load_binance_h2_selection_plan(plan_dir)
    output = Path(out_dir)
    symbols = (Path(plan_dir) / SYMBOLS_FILENAME).read_text(encoding="utf-8").splitlines()

    binding_payload = {
        "schema_version": SCHEMA_VERSION,
        "dataset_kind": "binance_h2_selection_collection_intent",
        "selection_manifest_digest": plan["digest"],
        "symbols_file_sha256": plan["outputs"]["symbols_file_sha256"],
        "venue": VENUE_BINANCE,
        "market": "spot",
        "window": [SELECTION_START.isoformat(), SELECTION_END.isoformat()],
        "venue_policy": VENUE_POLICIES[VENUE_BINANCE],
        "venue_policy_sha256": VENUE_POLICY_SHA256[VENUE_BINANCE],
    }
    binding = dict(binding_payload)
    binding["digest"] = sha256_of_text(canonical_dumps(binding_payload))
    binding_bytes = (canonical_dumps(binding) + "\n").encode("utf-8")

    if output.exists():
        if not output.is_dir() or output.is_symlink():
            raise CryptoSelectionError(f"venue selection output must be a directory: {output}")
        entries = {entry.name for entry in output.iterdir()}
        if entries:
            binding_path = output / BINDING_FILENAME
            if not binding_path.is_file() or binding_path.read_bytes() != binding_bytes:
                raise CryptoSelectionError(
                    "non-empty venue output is not bound byte-for-byte to this selection plan"
                )
            allowed = {
                BINDING_FILENAME,
                JOURNAL_FILENAME,
                "journal.lease",
                "raw",
                "receipts.jsonl",
                "series",
            }
            unknown = entries - allowed
            if unknown:
                raise CryptoSelectionError(
                    "venue output contains files outside the bound collector layout: "
                    f"{sorted(unknown)}"
                )
            journal_path = output / JOURNAL_FILENAME
            if journal_path.exists():
                records = read_journal(journal_path)
                verify_journal_chain(records)
                if not records:
                    raise CryptoSelectionError("existing venue journal is empty")
                header = records[0]
                expected_window = [SELECTION_START.isoformat(), SELECTION_END.isoformat()]
                if (
                    header.get("venue") != VENUE_BINANCE
                    or header.get("window") != expected_window
                    or header.get("policy") != VENUE_POLICIES[VENUE_BINANCE]
                    or header.get("policy_sha256") != VENUE_POLICY_SHA256[VENUE_BINANCE]
                ):
                    raise CryptoSelectionError(
                        "existing venue journal does not exactly match the bound "
                        "venue/window/policy"
                    )
            elif entries != {BINDING_FILENAME}:
                raise CryptoSelectionError(
                    "bound output has cache artifacts but no valid venue journal header"
                )
        else:
            atomic_write_text(output / BINDING_FILENAME, binding_bytes.decode("utf-8"))
    else:
        output.mkdir(parents=True)
        atomic_write_text(output / BINDING_FILENAME, binding_bytes.decode("utf-8"))

    # The immutable intent exists before the first possible HTTP request.  A
    # crash may therefore leave binding-only output, which is safe to resume.

    result = collect_venue_klines(
        output,
        symbols,
        venue=VENUE_BINANCE,
        start_date=SELECTION_START,
        end_date=SELECTION_END,
        fetcher=fetcher,
        clock=clock,
        sleep_seconds=sleep_seconds,
        timeout_seconds=timeout_seconds,
        max_symbols_per_run=max_symbols_per_run,
    )
    return result


__all__ = [
    "BINDING_FILENAME",
    "BINANCE_H2_SELECTION_SPEC",
    "MANIFEST_FILENAME",
    "SCHEMA_VERSION",
    "SELECTION_END",
    "SELECTION_POLICY",
    "SELECTION_POLICY_SHA256",
    "SELECTION_START",
    "SYMBOLS_FILENAME",
    "BinanceH2SelectionSpec",
    "CryptoSelectionError",
    "SelectionResearchReadiness",
    "SelectionPlanResult",
    "build_binance_h2_selection_plan",
    "collect_binance_h2_selection_klines",
    "evaluate_binance_h2_selection_research_readiness",
    "load_binance_h2_selection_plan",
    "require_binance_h2_selection_research_ready",
]
