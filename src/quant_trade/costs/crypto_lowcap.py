"""The real-cost model for low/mid-cap crypto, every input carrying evidence.

Three components make a round trip, and they are kept separable so nothing is
double-counted:

- **fees** (maker/taker, per fill) — ASSUMPTION class until venue fee bytes
  can be captured (the official fee pages are bot-walled from this
  environment; per the v9 rule, a fee without its bytes is an assumption
  wearing a better label);
- **execution cost vs mid** (half-spread + book slippage, per fill) —
  MEASURED by walking live order books (`quant_trade.costs.measure`);
- **not-executable** — a notional the visible book cannot fill has no cost;
  it has a refusal. ``None`` propagates, it is never extrapolated.

Evidence vocabulary is the repo's existing one
(`quant_trade.v9.cost_evidence.COST_EVIDENCE_CLASSES`): ASSUMPTION →
RECORDED_TEST → REAL_PUBLIC_RETAIL → REAL_ACCOUNT_SPECIFIC. "MEASURED" in
session documents maps to REAL_PUBLIC_RETAIL (public data, raw bytes
archived, sha256 recorded).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

from quant_trade.v9.cost_evidence import COST_EVIDENCE_CLASSES

#: Classes that may claim to be measurements of the real market.
MEASURED_CLASSES = ("REAL_PUBLIC_RETAIL", "REAL_ACCOUNT_SPECIFIC")

#: Market-cap tiers (USD). Low/mid cap is the object of study; mega/large are
#: kept for reference so the cost gradient across tiers is visible.
TIERS: tuple[tuple[str, float, float], ...] = (
    ("mega", 10e9, float("inf")),
    ("large", 1e9, 10e9),
    ("mid", 100e6, 1e9),
    ("low", 10e6, 100e6),
    ("micro", 1e6, 10e6),
)

#: Order notionals (USD) the model is calibrated at — small-capital sizes.
CALIBRATION_NOTIONALS: tuple[float, ...] = (100.0, 500.0, 1000.0, 5000.0, 10000.0)


class CostModelError(ValueError):
    """Raised when a cost input violates its own evidence declaration."""


def _require_utc_timestamp(value: str, *, field_name: str) -> None:
    """Require an explicit, zero-offset ISO-8601 timestamp.

    Treating a naive timestamp as UTC would make evidence capture time depend
    on an ambient timezone.  Provenance timestamps therefore have to carry a
    literal ``Z`` or ``+00:00`` offset.
    """

    if not isinstance(value, str) or not value.strip():
        raise CostModelError(f"{field_name} must be an explicit UTC timestamp")
    normalized = value.strip()
    try:
        parsed = datetime.fromisoformat(
            normalized[:-1] + "+00:00" if normalized.endswith("Z") else normalized
        )
    except ValueError as exc:
        raise CostModelError(f"{field_name} must be an explicit UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise CostModelError(f"{field_name} must be an explicit UTC timestamp")


def _require_sha256(value: str, *, field_name: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise CostModelError(f"{field_name} must be a lower-case SHA-256")


@dataclass(frozen=True)
class CostInput:
    """One priced input and where its number came from."""

    name: str
    value_bps: float
    evidence_class: str
    source: str
    captured_at_utc: str = ""
    raw_sha256: str = ""
    venue: str = ""
    endpoint: str = ""
    account_scope: str = ""
    venue_symbol: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if self.evidence_class not in COST_EVIDENCE_CLASSES:
            raise CostModelError(
                f"evidence_class must be one of {COST_EVIDENCE_CLASSES}, "
                f"got {self.evidence_class!r}"
            )
        if self.value_bps < 0:
            raise CostModelError(f"{self.name}: value_bps must be >= 0")
        if not self.source.strip():
            raise CostModelError(f"{self.name}: every cost input needs a source")
        if self.evidence_class in MEASURED_CLASSES:
            _require_sha256(self.raw_sha256, field_name=f"{self.name}: raw_sha256")
            _require_utc_timestamp(
                self.captured_at_utc,
                field_name=f"{self.name}: captured_at_utc",
            )
        if self.evidence_class == "REAL_ACCOUNT_SPECIFIC":
            required_metadata = {
                "venue": self.venue,
                "endpoint": self.endpoint,
                "account_scope": self.account_scope,
                "venue_symbol": self.venue_symbol,
            }
            missing = sorted(name for name, value in required_metadata.items() if not value.strip())
            if missing:
                raise CostModelError(
                    f"{self.name}: REAL_ACCOUNT_SPECIFIC fee evidence requires {', '.join(missing)}"
                )
            if self.venue.strip().lower() != self.venue:
                raise CostModelError(f"{self.name}: venue must be canonical lower-case")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


#: Base retail spot fees. ASSUMPTION class: the official fee pages returned
#: 403/JS-shell from this environment on 2026-08-05, so the numbers come from
#: vendor documentation without capturable bytes. They are the standard
#: non-VIP base rates and err high for anyone with volume discounts.
BYBIT_SPOT_TAKER_FEE = CostInput(
    name="bybit_spot_taker_fee",
    value_bps=10.0,
    evidence_class="ASSUMPTION",
    source="https://www.bybit.com/en/help-center/article/Trading-Fee-Structure",
    notes="base non-VIP retail rate; page bot-walled (HTTP 403), bytes not capturable",
)
BYBIT_SPOT_MAKER_FEE = CostInput(
    name="bybit_spot_maker_fee",
    value_bps=10.0,
    evidence_class="ASSUMPTION",
    source="https://www.bybit.com/en/help-center/article/Trading-Fee-Structure",
    notes="base non-VIP retail rate; page bot-walled (HTTP 403), bytes not capturable",
)


@dataclass(frozen=True)
class TierCostProfile:
    """Measured execution-cost calibration for one market-cap tier.

    ``exec_cost_bps_by_notional`` maps order notional (USD) to the median
    round-trip execution cost vs mid (buy walk + sell walk, fees excluded).
    ``None`` means the median book in this tier could not fill that notional —
    not executable, not "expensive".
    """

    tier: str
    market_cap_min_usd: float
    market_cap_max_usd: float
    sample_count: int
    half_spread_bps_p50: float
    half_spread_bps_p75: float
    exec_cost_bps_by_notional: dict[float, float | None]
    exec_cost_p75_bps_by_notional: dict[float, float | None]
    evidence_class: str
    source: str
    captured_at_utc: str
    manifest_sha256: str
    notes: str = ""
    #: Fraction of sampled books able to fill each notional. Quantiles at a
    #: notional with fraction < 1 cover only the books that could fill it —
    #: read them together or the tier looks cheaper than it is.
    executable_fraction_by_notional: dict[float, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.evidence_class not in COST_EVIDENCE_CLASSES:
            raise CostModelError(f"unknown evidence_class {self.evidence_class!r}")
        if not self.source.strip():
            raise CostModelError(f"{self.tier}: every cost profile needs a source")
        if self.evidence_class in MEASURED_CLASSES:
            _require_sha256(
                self.manifest_sha256,
                field_name=f"{self.tier}: manifest_sha256",
            )
            _require_utc_timestamp(
                self.captured_at_utc,
                field_name=f"{self.tier}: captured_at_utc",
            )

    def exec_cost_bps(self, notional_usd: float) -> float | None:
        """Round-trip execution cost at the closest calibrated notional at or
        above the requested size (conservative: never interpolates downward)."""
        eligible = [n for n in self.exec_cost_bps_by_notional if n >= notional_usd]
        if not eligible:
            return None
        return self.exec_cost_bps_by_notional[min(eligible)]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def tier_for_market_cap(market_cap_usd: float) -> str | None:
    """Tier name for a market cap, or None outside all bands (dust or mega+)."""
    for name, low, high in TIERS:
        if low <= market_cap_usd < high:
            return name
    return None


def round_trip_taker_cost_bps(
    profile: TierCostProfile,
    notional_usd: float,
    taker_fee: CostInput = BYBIT_SPOT_TAKER_FEE,
) -> float | None:
    """Full cost of entering and exiting ``notional_usd`` with market orders:
    two taker fees plus the measured round-trip execution cost vs mid.

    Returns ``None`` when the tier's median book cannot fill the size.
    """
    execution = profile.exec_cost_bps(notional_usd)
    if execution is None:
        return None
    return 2.0 * taker_fee.value_bps + execution


def max_viable_annual_turnover(
    round_trip_cost_bps: float,
    annual_cost_budget_bps: float,
) -> float:
    """How many full portfolio round trips per year the cost budget affords.

    Turnover convention: 1.0 = one full round trip of the whole portfolio
    (buy 100% NAV and later sell it). Annual cost drag = turnover x
    round-trip cost. The budget is an explicit ASSUMPTION the caller declares;
    there is no default, because the number *is* the decision.
    """
    if round_trip_cost_bps <= 0:
        raise CostModelError("round_trip_cost_bps must be positive")
    if annual_cost_budget_bps <= 0:
        raise CostModelError("annual_cost_budget_bps must be positive")
    return annual_cost_budget_bps / round_trip_cost_bps


def equivalent_total_window_turnover(annual_turnover: float, window_years: float) -> float:
    """Convert an annual turnover to the total-over-window convention used by
    the ETF promotion gate (whose 3.0 cap over a 5.75y window is ~0.52x/yr)."""
    if window_years <= 0:
        raise CostModelError("window_years must be positive")
    return annual_turnover * window_years


@dataclass(frozen=True)
class CostModelSummary:
    """Everything the cost model claims, with evidence attached, serialized
    for reports."""

    fees: tuple[CostInput, ...]
    profiles: tuple[TierCostProfile, ...]
    calibration_notionals: tuple[float, ...] = CALIBRATION_NOTIONALS
    not_measured: tuple[str, ...] = field(default_factory=lambda: NOT_MEASURED_COMPONENTS)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fees": [fee.to_dict() for fee in self.fees],
            "profiles": [profile.to_dict() for profile in self.profiles],
            "calibration_notionals": list(self.calibration_notionals),
            "not_measured": list(self.not_measured),
        }


#: Measured tier calibration from the 2026-08-05 live run: 57 Bybit spot books
#: sampled from the 2026-08-03 CMC point-in-time snapshot, 12 symbols per tier
#: by descending market cap (9 measurable in mega), stablecoins excluded. Raw
#: pages content-addressed with receipts under data/cache/crypto_costs/
#: (git-ignored); the manifest hash below is the verifiable reference.
#: Values are cross-sectional medians/p75 of ONE snapshot (2026-08-05T05:36Z),
#: rounded to 0.1 bps; intraday and historical variation are NOT_MEASURED.
_MEASUREMENT_SOURCE = (
    "bybit /v5/market/orderbook (limit=200) x 57 symbols; universe from CMC "
    "listings/historical 2026-08-03; manifest data/cache/crypto_costs/2026-08-05"
)
_MEASUREMENT_CAPTURED_AT = "2026-08-05T05:36:01Z"
_MEASUREMENT_MANIFEST_SHA256 = "b983be0daefb1cccff6df38e0a688bc022c5151e27662b1b612cfa5461bb5928"


def _measured_profile(
    tier: str,
    sample_count: int,
    half_spread_p50: float,
    half_spread_p75: float,
    p50: dict[float, float | None],
    p75: dict[float, float | None],
    executable: dict[float, float],
    notes: str = "",
) -> TierCostProfile:
    bounds = {name: (low, high) for name, low, high in TIERS}
    low, high = bounds[tier]
    return TierCostProfile(
        tier=tier,
        market_cap_min_usd=low,
        market_cap_max_usd=high,
        sample_count=sample_count,
        half_spread_bps_p50=half_spread_p50,
        half_spread_bps_p75=half_spread_p75,
        exec_cost_bps_by_notional=p50,
        exec_cost_p75_bps_by_notional=p75,
        evidence_class="REAL_PUBLIC_RETAIL",
        source=_MEASUREMENT_SOURCE,
        captured_at_utc=_MEASUREMENT_CAPTURED_AT,
        manifest_sha256=_MEASUREMENT_MANIFEST_SHA256,
        notes=notes,
        executable_fraction_by_notional=executable,
    )


DEFAULT_TIER_PROFILES: tuple[TierCostProfile, ...] = (
    _measured_profile(
        "mega",
        9,
        0.7,
        0.8,
        {100.0: 1.4, 500.0: 1.4, 1000.0: 1.4, 5000.0: 2.7, 10000.0: 4.1},
        {100.0: 1.7, 500.0: 1.8, 1000.0: 1.9, 5000.0: 3.7, 10000.0: 5.3},
        {100.0: 1.0, 500.0: 1.0, 1000.0: 1.0, 5000.0: 1.0, 10000.0: 1.0},
    ),
    _measured_profile(
        "large",
        12,
        1.3,
        2.7,
        {100.0: 3.7, 500.0: 5.5, 1000.0: 6.8, 5000.0: 11.3, 10000.0: 15.7},
        {100.0: 5.4, 500.0: 7.1, 1000.0: 9.3, 5000.0: 16.1, 10000.0: 20.8},
        {100.0: 1.0, 500.0: 1.0, 1000.0: 1.0, 5000.0: 1.0, 10000.0: 1.0},
    ),
    _measured_profile(
        "mid",
        12,
        2.6,
        7.4,
        {100.0: 6.7, 500.0: 14.5, 1000.0: 14.8, 5000.0: 27.2, 10000.0: 43.9},
        {100.0: 14.7, 500.0: 16.1, 1000.0: 23.7, 5000.0: 47.0, 10000.0: 57.9},
        {100.0: 1.0, 500.0: 1.0, 1000.0: 1.0, 5000.0: 1.0, 10000.0: 1.0},
    ),
    _measured_profile(
        "low",
        12,
        3.7,
        5.3,
        {100.0: 12.2, 500.0: 18.0, 1000.0: 23.3, 5000.0: 52.5, 10000.0: 88.2},
        {100.0: 12.9, 500.0: 19.6, 1000.0: 25.4, 5000.0: 68.6, 10000.0: 142.3},
        {100.0: 1.0, 500.0: 1.0, 1000.0: 1.0, 5000.0: 1.0, 10000.0: 0.917},
    ),
    _measured_profile(
        "micro",
        12,
        11.7,
        18.8,
        {100.0: 27.8, 500.0: 46.7, 1000.0: 59.5, 5000.0: 229.0, 10000.0: 223.1},
        {100.0: 52.2, 500.0: 84.4, 1000.0: 124.6, 5000.0: 373.5, 10000.0: 326.4},
        {100.0: 1.0, 500.0: 1.0, 1000.0: 1.0, 5000.0: 0.917, 10000.0: 0.75},
        notes=(
            "p50 at $10k sits below $5k because the books unable to fill $10k "
            "drop out of that quantile (composition effect); read with "
            "executable_fraction_by_notional"
        ),
    ),
)

#: Components this model does NOT price, declared so their absence is visible.
NOT_MEASURED_COMPONENTS: tuple[str, ...] = (
    "historical spread/depth series (only a live cross-section was measured)",
    "intraday spread variation (single-snapshot measurement)",
    "perp funding paid/received (spot-only model)",
    "withdrawal fees and fiat on/off-ramp costs",
    "adverse selection / market impact beyond the visible book",
    "maker fill probability (taker-only round trip is priced)",
)

__all__ = [
    "BYBIT_SPOT_MAKER_FEE",
    "BYBIT_SPOT_TAKER_FEE",
    "CALIBRATION_NOTIONALS",
    "DEFAULT_TIER_PROFILES",
    "CostInput",
    "CostModelError",
    "CostModelSummary",
    "MEASURED_CLASSES",
    "NOT_MEASURED_COMPONENTS",
    "TIERS",
    "TierCostProfile",
    "equivalent_total_window_turnover",
    "max_viable_annual_turnover",
    "round_trip_taker_cost_bps",
    "tier_for_market_cap",
]
