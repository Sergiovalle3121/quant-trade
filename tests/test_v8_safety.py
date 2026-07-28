"""V8 safety invariants: no orders, no funds, no miners, no cloud spend.

These tests are structural rather than behavioural. They assert that the
dangerous verbs do not exist in the V8 surface at all, because a capability
that is absent cannot be reached by a bug, a config mistake, or a future
refactor that "just wires it up".
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from pathlib import Path

import quant_trade.v8 as v8_package

#: Verb fragments that would mean spending money or moving funds.
FORBIDDEN_CALLABLES = (
    "place_order",
    "submit_order",
    "create_order",
    "cancel_order",
    "buy_hashrate",
    "purchase_hashrate",
    "deposit",
    "withdraw",
    "transfer_funds",
    "start_miner",
    "provision_instance",
    "run_instance",
    "create_instance",
    "launch_instance",
)

#: Anything that looks like a credential must never appear in the source.
FORBIDDEN_SOURCE_TOKENS = (
    "api_secret",
    "apisecret",
    "seed_phrase",
    "mnemonic",
    "private_key",
    "X-BAPI-SIGN",
    "OK-ACCESS-KEY",
)


def _v8_modules():
    for info in pkgutil.iter_modules(v8_package.__path__):
        yield importlib.import_module(f"quant_trade.v8.{info.name}")


def test_v8_exposes_no_trading_or_funding_verbs() -> None:
    offenders = []
    for module in _v8_modules():
        for name, obj in vars(module).items():
            if name.startswith("_") or not callable(obj):
                continue
            lowered = name.lower()
            if any(bad in lowered for bad in FORBIDDEN_CALLABLES):
                offenders.append(f"{module.__name__}.{name}")
    assert offenders == [], offenders


def test_v8_classes_expose_no_trading_or_funding_methods() -> None:
    offenders = []
    for module in _v8_modules():
        for class_name, obj in vars(module).items():
            if not inspect.isclass(obj) or obj.__module__ != module.__name__:
                continue
            for method in dir(obj):
                if not callable(getattr(obj, method, None)):
                    continue  # a field named `deposited_usd` describes, it does not act
                lowered = method.lower()
                if any(bad in lowered for bad in FORBIDDEN_CALLABLES):
                    offenders.append(f"{module.__name__}.{class_name}.{method}")
    assert offenders == [], offenders


def test_v8_source_carries_no_credential_material() -> None:
    offenders = []
    for path in sorted(Path("src/quant_trade/v8").glob("*.py")):
        text = path.read_text(encoding="utf-8").lower()
        for token in FORBIDDEN_SOURCE_TOKENS:
            if token.lower() in text:
                offenders.append(f"{path}: {token}")
    assert offenders == [], offenders


def test_v8_never_reads_credentials_from_the_environment() -> None:
    offenders = []
    for path in sorted(Path("src/quant_trade/v8").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "os.environ" in text or "getenv" in text:
            offenders.append(str(path))
    assert offenders == [], offenders


def test_only_official_venue_and_marketplace_hosts_appear() -> None:
    """No mirrors, proxies, VPN exits or third-party redistributors."""
    import re

    allowed = {
        "api.bybit.com",
        "www.okx.com",
        "api2.nicehash.com",
        "api.bytick.com",
        "api.bybit.nl",
        "aws.okx.com",
        "my.okx.com",
    }
    found: set[str] = set()
    for path in sorted(Path("src/quant_trade/v8").glob("*.py")):
        for match in re.findall(r"https://([A-Za-z0-9.\-]+)", path.read_text(encoding="utf-8")):
            found.add(match)
    assert found <= allowed, sorted(found - allowed)


def test_mining_artifacts_never_authorise_a_purchase() -> None:
    from quant_trade.v8.hashrate_market import MarketplaceScan, MiningOpportunity

    scan = MarketplaceScan(provider="nicehash", status="DISCOVERY_ONLY", scanned_at_utc="x")
    payload = scan.to_dict()
    assert payload["purchase_authorized"] is False
    assert payload["deposit_authorized"] is False
    assert payload["withdrawal_authorized"] is False
    assert payload["miners_started"] == 0

    opportunity = MiningOpportunity(
        opportunity_id="x", provider="nicehash", algorithm_id="sha256", status="DISCOVERY_ONLY"
    )
    assert opportunity.to_dict()["purchase_authorized"] is False


def test_paper_artifacts_never_authorise_real_money() -> None:
    from quant_trade.v8.paper_launch import SAFETY_POSTURE, not_started_report

    assert SAFETY_POSTURE["real_money_authorized"] is False
    assert SAFETY_POSTURE["order_routing_enabled"] is False
    assert SAFETY_POSTURE["credentials_required"] is False
    assert SAFETY_POSTURE["venue_connectivity"] == "market_data_read_only"
    assert not_started_report("x").to_dict()["safety"]["deposits_enabled"] is False


def test_canary_artifact_never_authorises_real_money() -> None:
    from quant_trade.v8.canary import evaluate_canary_readiness

    payload = evaluate_canary_readiness(
        evaluated_at_utc="2026-07-28T00:00:00Z",
        paper_status=None,
        owner_budget_usd=1_000_000.0,
        exchange_and_jurisdiction_confirmed=True,
        loss_limits_configured={"per_trade": 1.0, "daily": 1.0, "total": 1.0},
        credentials_delivery_mechanism_confirmed=True,
    ).to_dict()
    assert payload["canary_authorized"] is False
    assert payload["real_money_authorized"] is False


def test_backfill_sends_no_authentication_headers() -> None:
    from quant_trade.v8.backfill import USER_AGENT
    import quant_trade.v8.backfill as backfill

    source = Path(inspect.getfile(backfill)).read_text(encoding="utf-8")
    assert "Authorization" not in source
    assert "api-key" not in source.lower()
    assert "read-only" in USER_AGENT


def test_cloud_hashing_remains_blocked() -> None:
    """AWS/Alibaba may be a control plane; they may never hash."""
    from quant_trade.cloud_rental.models import CloudProvider, WorkloadPurpose
    from quant_trade.cloud_rental.policy import evaluate_provider_policy

    for provider in (CloudProvider.AWS, CloudProvider.ALIBABA):
        verdict = evaluate_provider_policy(
            provider,
            WorkloadPurpose.HASHING_WORKER,
            None,
            evaluated_at_utc="2026-07-28T00:00:00Z",
        )
        assert verdict.status.startswith("BLOCKED"), (provider, verdict.status)
