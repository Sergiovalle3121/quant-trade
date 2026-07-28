"""Fee schedules as evidence, not as constants.

V8 priced every campaign from a hardcoded stack labelled
``ASSUMPTION_UNVERIFIED``. That was honest but useless: nothing could ever
promote, and the numbers were nobody's actual fees. V9 replaces the constants
with a bundle that has to come from somewhere and says where.

A bundle records, per venue and per instrument: maker and taker rates, the fee
tier they belong to, the currency, any minimum-fee floor, when the schedule
became effective and when the evidence expires, the official source, the
SHA-256 of the raw response, the parser version, and both the capture and
server timestamps.

Four evidence classes, and only the top two can support a promotion:

``REAL_ACCOUNT_SPECIFIC``
    the account's own rates, from the venue's authenticated read-only fee
    endpoint. What the operator will actually pay.
``REAL_PUBLIC_RETAIL``
    the venue's published retail schedule. Real, and conservative for anyone
    with a VIP tier.
``RECORDED_TEST``
    a recorded response replayed offline. Exercises the path; promotes nothing.
``ASSUMPTION``
    a number somebody typed. Promotes nothing, ever.

**No credential ever enters this repository.** The authenticated path is
defined as a request *specification* the operator runs on their own host; what
comes back here is the response bytes. There is no signing code, no key
parameter, and no environment lookup — a test enforces all three.
"""

from __future__ import annotations

import calendar
import json
import math
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_bytes, sha256_of_text

#: Evidence classes, weakest first.
COST_EVIDENCE_CLASSES = (
    "ASSUMPTION",
    "RECORDED_TEST",
    "REAL_PUBLIC_RETAIL",
    "REAL_ACCOUNT_SPECIFIC",
)

#: Classes V9 policy allows to support a paper promotion.
PROMOTABLE_CLASSES = ("REAL_PUBLIC_RETAIL", "REAL_ACCOUNT_SPECIFIC")

#: Official fee endpoints. The account-specific ones are authenticated and are
#: run by the operator on their own host; only the response bytes come here.
FEE_ENDPOINTS = {
    "bybit": {
        "account_specific": "https://api.bybit.com/v5/account/fee-rate",
        "public_reference": "https://api.bybit.com/v5/market/instruments-info",
        "auth": "authenticated read-only; run on the operator's host",
    },
    "okx": {
        "account_specific": "https://www.okx.com/api/v5/account/trade-fee",
        "public_reference": "https://www.okx.com/api/v5/public/instruments",
        "auth": "authenticated read-only; run on the operator's host",
    },
}

LEG_SPOT = "spot"
LEG_PERP = "perp"
LEGS = (LEG_SPOT, LEG_PERP)


class CostEvidenceError(ValueError):
    """A fee input that cannot be trusted to price anything."""


def _parse_utc(value: str) -> int:
    text = value.strip().replace("Z", "")
    for pattern in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return int(calendar.timegm(time.strptime(text, pattern)) * 1000)
        except ValueError:
            continue
    raise CostEvidenceError(f"cannot parse {value!r} as an ISO-8601 UTC timestamp")


@dataclass(frozen=True)
class FeeSchedule:
    """One venue/instrument/leg fee record, with its provenance."""

    venue: str
    instrument: str
    leg: str
    maker_bps: float
    taker_bps: float
    fee_tier: str
    currency: str
    minimum_fee: float
    effective_from_utc: str
    expires_at_utc: str
    source_url: str
    raw_sha256: str
    parser_version: str
    evidence_class: str
    captured_at_utc: str
    server_timestamp_utc: str = ""

    def __post_init__(self) -> None:
        if self.leg not in LEGS:
            raise CostEvidenceError(f"leg must be one of {LEGS}")
        if self.evidence_class not in COST_EVIDENCE_CLASSES:
            raise CostEvidenceError(f"evidence_class must be one of {COST_EVIDENCE_CLASSES}")
        for name in ("maker_bps", "taker_bps", "minimum_fee"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0:
                raise CostEvidenceError(f"{name} must be finite and >= 0")
        if not self.source_url.strip():
            raise CostEvidenceError("every fee schedule needs an official source URL")
        if self.evidence_class in PROMOTABLE_CLASSES and not self.raw_sha256.strip():
            raise CostEvidenceError(
                f"{self.evidence_class} requires the SHA-256 of the raw response; "
                "a real fee schedule without its bytes is an assumption wearing a "
                "better label"
            )
        if _parse_utc(self.expires_at_utc) <= _parse_utc(self.effective_from_utc):
            raise CostEvidenceError("expires_at_utc must be after effective_from_utc")

    @property
    def promotable(self) -> bool:
        return self.evidence_class in PROMOTABLE_CLASSES

    def is_stale_at(self, now_utc: str) -> bool:
        return _parse_utc(now_utc) > _parse_utc(self.expires_at_utc)

    def effective_at(self, now_utc: str) -> bool:
        return _parse_utc(now_utc) >= _parse_utc(self.effective_from_utc)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["promotable"] = self.promotable
        return payload


@dataclass
class CostEvidenceBundle:
    """Every fee a strategy pays on one venue, with provenance for each."""

    venue: str
    schedules: tuple[FeeSchedule, ...]
    captured_at_utc: str
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.schedules:
            raise CostEvidenceError("a cost bundle needs at least one fee schedule")
        wrong = [s for s in self.schedules if s.venue != self.venue]
        if wrong:
            raise CostEvidenceError(
                f"bundle is labelled {self.venue!r} but carries schedules for "
                f"{sorted({s.venue for s in wrong})}: one venue's fees may never "
                "price another venue's leg"
            )

    @property
    def bundle_sha256(self) -> str:
        return sha256_of_text(
            canonical_dumps(
                {
                    "venue": self.venue,
                    "schedules": [s.to_dict() for s in self.schedules],
                }
            )
        )

    @property
    def weakest_evidence_class(self) -> str:
        return min(
            (s.evidence_class for s in self.schedules),
            key=COST_EVIDENCE_CLASSES.index,
        )

    @property
    def promotable(self) -> bool:
        return all(s.promotable for s in self.schedules)

    def schedule(self, leg: str) -> FeeSchedule:
        for candidate in self.schedules:
            if candidate.leg == leg:
                return candidate
        raise CostEvidenceError(f"bundle for {self.venue} has no {leg} schedule")

    def taker_bps(self, leg: str) -> float:
        return self.schedule(leg).taker_bps

    def validate(self, *, now_utc: str, required_legs: tuple[str, ...] = LEGS) -> list[str]:
        """Every reason this bundle cannot price a promotable campaign."""
        problems: list[str] = []
        present = {s.leg for s in self.schedules}
        for leg in required_legs:
            if leg not in present:
                problems.append(f"{self.venue}: no {leg} fee schedule in the bundle")
        for schedule in self.schedules:
            if not schedule.promotable:
                problems.append(
                    f"{self.venue}:{schedule.leg} is {schedule.evidence_class}, which "
                    "cannot support a promotion"
                )
            if schedule.is_stale_at(now_utc):
                problems.append(
                    f"{self.venue}:{schedule.leg} evidence expired at "
                    f"{schedule.expires_at_utc}, before {now_utc}"
                )
            if not schedule.effective_at(now_utc):
                problems.append(
                    f"{self.venue}:{schedule.leg} is not yet effective "
                    f"(from {schedule.effective_from_utc})"
                )
        return problems

    def to_dict(self) -> dict[str, Any]:
        return {
            "venue": self.venue,
            "captured_at_utc": self.captured_at_utc,
            "bundle_sha256": self.bundle_sha256,
            "weakest_evidence_class": self.weakest_evidence_class,
            "promotable": self.promotable,
            "schedules": [s.to_dict() for s in self.schedules],
            "notes": list(self.notes),
        }


def parse_bybit_fee_rate(
    raw: bytes,
    *,
    instrument: str,
    captured_at_utc: str,
    evidence_class: str = "REAL_ACCOUNT_SPECIFIC",
    effective_from_utc: str,
    expires_at_utc: str,
    parser_version: str = "v9.1",
) -> list[FeeSchedule]:
    """Parse Bybit ``/v5/account/fee-rate``.

    Bybit reports rates as fractions (``"0.00055"``); they are converted to
    basis points here so every downstream unit is the same.
    """
    payload = json.loads(raw.decode("utf-8"))
    if int(payload.get("retCode", -1)) != 0:
        raise CostEvidenceError(
            f"bybit fee-rate error retCode={payload.get('retCode')} "
            f"retMsg={payload.get('retMsg')!r}"
        )
    raw_sha = sha256_of_bytes(raw)
    schedules: list[FeeSchedule] = []
    for entry in payload.get("result", {}).get("list", []) or []:
        symbol = str(entry.get("symbol", ""))
        if symbol != instrument:
            continue
        leg = LEG_SPOT if str(entry.get("category", "")) == "spot" else LEG_PERP
        schedules.append(
            FeeSchedule(
                venue="bybit",
                instrument=symbol,
                leg=leg,
                maker_bps=float(entry["makerFeeRate"]) * 10_000.0,
                taker_bps=float(entry["takerFeeRate"]) * 10_000.0,
                fee_tier=str(entry.get("feeTier", "account")),
                currency=str(entry.get("currency", "USDT")),
                minimum_fee=float(entry.get("minFee", 0.0) or 0.0),
                effective_from_utc=effective_from_utc,
                expires_at_utc=expires_at_utc,
                source_url=FEE_ENDPOINTS["bybit"]["account_specific"],
                raw_sha256=raw_sha,
                parser_version=parser_version,
                evidence_class=evidence_class,
                captured_at_utc=captured_at_utc,
                server_timestamp_utc=str(payload.get("time", "")),
            )
        )
    if not schedules:
        raise CostEvidenceError(f"bybit fee-rate response carries no row for {instrument!r}")
    return schedules


def parse_okx_trade_fee(
    raw: bytes,
    *,
    instrument: str,
    leg: str,
    captured_at_utc: str,
    evidence_class: str = "REAL_ACCOUNT_SPECIFIC",
    effective_from_utc: str,
    expires_at_utc: str,
    parser_version: str = "v9.1",
) -> list[FeeSchedule]:
    """Parse OKX ``/api/v5/account/trade-fee``.

    OKX reports fees as **negative** fractions when they are charges (``"-
    0.0005"``) and positive when they are rebates. The sign is normalised here
    so a rebate never reads as a cost, and a cost never reads as income.
    """
    payload = json.loads(raw.decode("utf-8"))
    if str(payload.get("code", "")) != "0":
        raise CostEvidenceError(
            f"okx trade-fee error code={payload.get('code')!r} msg={payload.get('msg')!r}"
        )
    raw_sha = sha256_of_bytes(raw)
    schedules: list[FeeSchedule] = []
    for entry in payload.get("data", []) or []:
        maker = -float(entry["maker"]) * 10_000.0
        taker = -float(entry["taker"]) * 10_000.0
        schedules.append(
            FeeSchedule(
                venue="okx",
                instrument=instrument,
                leg=leg,
                maker_bps=max(0.0, maker),
                taker_bps=max(0.0, taker),
                fee_tier=str(entry.get("level", "account")),
                currency=str(entry.get("ccy", "USDT")),
                minimum_fee=0.0,
                effective_from_utc=effective_from_utc,
                expires_at_utc=expires_at_utc,
                source_url=FEE_ENDPOINTS["okx"]["account_specific"],
                raw_sha256=raw_sha,
                parser_version=parser_version,
                evidence_class=evidence_class,
                captured_at_utc=captured_at_utc,
                server_timestamp_utc=str(entry.get("ts", "")),
            )
        )
    if not schedules:
        raise CostEvidenceError("okx trade-fee response carries no rows")
    return schedules


def assumption_bundle(venue: str, *, captured_at_utc: str) -> CostEvidenceBundle:
    """The published-retail fallback, labelled for what it is.

    Conservative by construction — at or above each venue's public retail rate,
    so it can reject a strategy but never flatter one. It is ``ASSUMPTION``
    class and therefore cannot promote anything.
    """
    perp_taker = {"bybit": 5.5, "okx": 5.0}[venue]
    instrument = "BTCUSDT" if venue == "bybit" else "BTC-USDT"

    def retail(leg: str, symbol: str, maker: float, taker: float) -> FeeSchedule:
        return FeeSchedule(
            venue=venue,
            instrument=symbol,
            leg=leg,
            maker_bps=maker,
            taker_bps=taker,
            fee_tier="published_retail",
            currency="USDT",
            minimum_fee=0.0,
            effective_from_utc="2020-01-01T00:00:00Z",
            expires_at_utc="2099-01-01T00:00:00Z",
            source_url=FEE_ENDPOINTS[venue]["public_reference"],
            raw_sha256="",
            parser_version="v9.1",
            evidence_class="ASSUMPTION",
            captured_at_utc=captured_at_utc,
        )

    return CostEvidenceBundle(
        venue=venue,
        captured_at_utc=captured_at_utc,
        schedules=(
            retail(LEG_SPOT, instrument, 10.0, 10.0),
            retail(
                LEG_PERP,
                instrument if venue == "bybit" else "BTC-USDT-SWAP",
                perp_taker / 2.0,
                perp_taker,
            ),
        ),
        notes=[
            "published retail rates, typed from documentation and not captured "
            "from the venue; conservative in direction and non-promotable by class",
        ],
    )


@dataclass
class BundleSet:
    """The bundles a campaign needs. H3 requires two independent ones."""

    bundles: dict[str, CostEvidenceBundle] = field(default_factory=dict)

    def add(self, bundle: CostEvidenceBundle) -> None:
        self.bundles[bundle.venue] = bundle

    def require(self, venues: tuple[str, ...], *, now_utc: str) -> list[str]:
        """Every reason this set cannot price a promotable campaign."""
        problems: list[str] = []
        for venue in venues:
            bundle = self.bundles.get(venue)
            if bundle is None:
                problems.append(f"no cost evidence bundle for {venue}")
                continue
            problems.extend(bundle.validate(now_utc=now_utc))
        if len(venues) > 1:
            digests = {v: self.bundles[v].bundle_sha256 for v in venues if v in self.bundles}
            if len(set(digests.values())) < len(digests):
                problems.append(
                    "two venues share one cost bundle; a cross-venue strategy must "
                    "price each leg with that venue's own schedule"
                )
        return problems

    @property
    def promotable(self) -> bool:
        return bool(self.bundles) and all(b.promotable for b in self.bundles.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "venues": sorted(self.bundles),
            "promotable": self.promotable,
            "bundles": {v: b.to_dict() for v, b in sorted(self.bundles.items())},
        }


def load_bundle(path: str | Path) -> CostEvidenceBundle:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    known = {f for f in FeeSchedule.__dataclass_fields__}
    schedules = tuple(
        FeeSchedule(**{k: v for k, v in entry.items() if k in known})
        for entry in payload["schedules"]
    )
    return CostEvidenceBundle(
        venue=str(payload["venue"]),
        schedules=schedules,
        captured_at_utc=str(payload.get("captured_at_utc", "")),
        notes=list(payload.get("notes", [])),
    )


def operator_capture_instructions(venue: str) -> dict[str, Any]:
    """What the operator runs on their own host. No secret comes here.

    The authenticated fee endpoints need an API key. This repository never
    asks for one, never stores one and never signs a request; the operator
    captures the response themselves and imports the bytes.
    """
    endpoints = FEE_ENDPOINTS[venue]
    return {
        "venue": venue,
        "endpoint": endpoints["account_specific"],
        "auth": endpoints["auth"],
        "permissions_required": "read-only; NO trade, NO withdraw, NO transfer",
        "what_to_send_back": "the raw response bytes only",
        "never_send": [
            "API key",
            "API secret",
            "passphrase",
            "seed phrase",
            "wallet key",
        ],
        "import_command": (
            f"quant-trade v9 cost-import --venue {venue} --raw <path-to-response.json> "
            "--effective-from <iso> --expires-at <iso>"
        ),
        "note": (
            "This tooling contains no signing code and reads no credential from "
            "the environment. Capture on your host, import the bytes here."
        ),
    }


__all__ = [
    "COST_EVIDENCE_CLASSES",
    "FEE_ENDPOINTS",
    "LEGS",
    "LEG_PERP",
    "LEG_SPOT",
    "PROMOTABLE_CLASSES",
    "BundleSet",
    "CostEvidenceBundle",
    "CostEvidenceError",
    "FeeSchedule",
    "assumption_bundle",
    "load_bundle",
    "operator_capture_instructions",
    "parse_bybit_fee_rate",
    "parse_okx_trade_fee",
]
