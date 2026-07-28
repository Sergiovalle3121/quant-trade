"""Reachability probe for the official venue domains.

When acquisition fails, *why* it failed is itself evidence, and it has to be
recorded with the same rigour as a successful capture — otherwise "we could
not download the data" is indistinguishable from "we did not try".

The probe attempts each venue's primary documented domain and then only the
alternative domains the venue itself publishes (Bybit's ``api.bytick.com`` and
its regional entity hosts; OKX's ``aws.okx.com`` and regional apps). It does
**not** try proxies, VPN exits, mirrors, cached third-party copies, or
anything else that would route around a restriction: if an organisation's
egress policy or a venue's regional policy blocks a host, the blocked host is
the finding.

Every attempt is recorded with the verbatim error string, the host, the
timestamp and the outcome class, so a reader can tell a policy denial (403 on
CONNECT) apart from DNS failure, TLS failure, or a venue-side error.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlsplit

from quant_trade.v8.venues import BYBIT_HOST, OKX_HOST

#: Documented domains, per venue, in the order the probe tries them. Only
#: hosts the venue itself publishes as official API endpoints appear here.
OFFICIAL_DOMAINS: dict[str, tuple[tuple[str, str], ...]] = {
    "bybit": (
        ("https://api.bybit.com", "primary documented API domain"),
        ("https://api.bytick.com", "venue-published alternative domain"),
        ("https://api.bybit.nl", "venue-published Netherlands entity domain"),
    ),
    "okx": (
        ("https://www.okx.com", "primary documented API domain"),
        ("https://aws.okx.com", "venue-published alternative API domain"),
        ("https://my.okx.com", "venue-published regional app domain"),
    ),
}

#: Path appended to each host: the cheapest documented public endpoint.
PROBE_PATHS = {"bybit": "/v5/market/time", "okx": "/api/v5/public/time"}

OUTCOME_REACHABLE = "REACHABLE"
OUTCOME_POLICY_BLOCKED = "BLOCKED_EGRESS_POLICY"
OUTCOME_DNS_FAILURE = "DNS_FAILURE"
OUTCOME_TLS_FAILURE = "TLS_FAILURE"
OUTCOME_TRANSPORT_FAILURE = "TRANSPORT_FAILURE"
OUTCOME_HTTP_ERROR = "HTTP_ERROR"


def classify_error(error: str) -> str:
    """Classify a transport failure from its verbatim message.

    The distinction that matters economically: a *policy* denial is a
    permission problem a human can resolve, while DNS/TLS failures are
    environment problems. Guessing wrong sends the next operator down the
    wrong path, so unrecognised errors stay ``TRANSPORT_FAILURE`` rather than
    being forced into a category.
    """
    lowered = error.lower()
    if "connect tunnel failed" in lowered or "403" in lowered or "407" in lowered:
        return OUTCOME_POLICY_BLOCKED
    if "name or service not known" in lowered or "nodename nor servname" in lowered:
        return OUTCOME_DNS_FAILURE
    if "certificate" in lowered or "ssl" in lowered or "tls" in lowered:
        return OUTCOME_TLS_FAILURE
    return OUTCOME_TRANSPORT_FAILURE


@dataclass
class DomainProbe:
    venue: str
    host: str
    url: str
    role: str
    outcome: str
    http_status: int | None = None
    error: str = ""
    attempted_at_utc: str = ""
    elapsed_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProbeReport:
    attempted_at_utc: str
    probes: list[DomainProbe] = field(default_factory=list)
    reachable_venues: list[str] = field(default_factory=list)
    blocked_venues: list[str] = field(default_factory=list)

    @property
    def any_reachable(self) -> bool:
        return bool(self.reachable_venues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact": "V8_NETWORK_REACHABILITY_PROBE",
            "attempted_at_utc": self.attempted_at_utc,
            "probes": [p.to_dict() for p in self.probes],
            "reachable_venues": sorted(self.reachable_venues),
            "blocked_venues": sorted(self.blocked_venues),
            "any_reachable": self.any_reachable,
            "policy": (
                "Only venue-published official domains are attempted. Proxies, "
                "VPN exits, mirrors and third-party redistributors are never "
                "used to route around a regional or organisational restriction."
            ),
        }


def probe_domains(
    *,
    fetcher: Callable[[str], tuple[int, bytes, dict[str, str]]] | None = None,
    venues: tuple[str, ...] = ("bybit", "okx"),
    timeout_seconds: float = 15.0,
    clock: Callable[[], float] | None = None,
    now_utc: str | None = None,
) -> ProbeReport:
    """Probe each venue's documented domains and record what happened."""
    from quant_trade.v8.backfill import http_get

    monotonic = clock or time.monotonic
    active = fetcher or (lambda url: http_get(url, timeout_seconds=timeout_seconds))
    stamp = now_utc or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    report = ProbeReport(attempted_at_utc=stamp)

    for venue in venues:
        reachable = False
        for host_url, role in OFFICIAL_DOMAINS[venue]:
            url = f"{host_url}{PROBE_PATHS[venue]}"
            started = monotonic()
            probe = DomainProbe(
                venue=venue,
                host=urlsplit(host_url).netloc,
                url=url,
                role=role,
                outcome=OUTCOME_REACHABLE,
                attempted_at_utc=stamp,
            )
            try:
                status, _body, _headers = active(url)
            except Exception as exc:  # noqa: BLE001 — the verbatim error IS the evidence
                probe.error = f"{type(exc).__name__}: {exc}"
                probe.outcome = classify_error(probe.error)
            else:
                probe.http_status = status
                if status != 200:
                    probe.outcome = OUTCOME_HTTP_ERROR
                    probe.error = f"HTTP {status}"
                else:
                    reachable = True
            probe.elapsed_ms = int((monotonic() - started) * 1000)
            report.probes.append(probe)
            if reachable:
                break
        (report.reachable_venues if reachable else report.blocked_venues).append(venue)
    return report


def primary_hosts() -> dict[str, str]:
    return {
        "bybit": urlsplit(BYBIT_HOST).netloc,
        "okx": urlsplit(OKX_HOST).netloc,
    }


__all__ = [
    "OFFICIAL_DOMAINS",
    "OUTCOME_DNS_FAILURE",
    "OUTCOME_HTTP_ERROR",
    "OUTCOME_POLICY_BLOCKED",
    "OUTCOME_REACHABLE",
    "OUTCOME_TLS_FAILURE",
    "OUTCOME_TRANSPORT_FAILURE",
    "PROBE_PATHS",
    "DomainProbe",
    "ProbeReport",
    "classify_error",
    "primary_hosts",
    "probe_domains",
]
