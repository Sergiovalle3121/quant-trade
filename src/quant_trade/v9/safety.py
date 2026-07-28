"""The execution boundary, written as data and checked by inspection.

A comment saying "we never submit live orders" is worth nothing; what matters
is whether a code path exists that could. So this module states the boundary
as a table of flags, and the accompanying tests verify each one against the
package itself — by importing every V9 module and looking for the names,
imports and endpoint strings that a real order, a real purchase or a real
withdrawal would need.

The flags below are fixed. Nothing in V9 sets them, and there is no function
here that flips one: enabling live execution is a code change a human makes
and reviews, not a configuration this repository can reach.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import re
from typing import Any

#: The non-negotiable execution flags. All DISABLED, none configurable.
EXECUTION_FLAGS: dict[str, str] = {
    "LIVE_ORDER_SUBMISSION": "DISABLED",
    "LIVE_BROKER_EXECUTION": "DISABLED",
    "MINING_PURCHASE_EXECUTION": "DISABLED",
    "DEPOSIT_EXECUTION": "DISABLED",
    "WITHDRAWAL_EXECUTION": "DISABLED",
    "WALLET_SIGNING": "DISABLED",
    "AWS_ALIBABA_HASHING": "PROHIBITED",
    "CLOUD_RESOURCE_CREATION": "DISABLED",
    "EXTERNAL_SPEND": "DISABLED",
}

#: Module-level names that would indicate a transacting code path.
FORBIDDEN_NAMES = (
    "submit_live_order",
    "place_live_order",
    "buy_hashrate",
    "purchase_hashrate",
    "deposit_funds",
    "withdraw_funds",
    "sign_transaction",
    "sign_withdrawal",
    "create_instance",
    "run_instances",
    "launch_miner",
    "start_miner",
)

#: Patterns that would indicate credential handling or request signing. A
#: read-only adapter needs none of them; their absence is the evidence.
CREDENTIAL_PATTERNS = (
    r"\bimport hmac\b",
    r"\bhmac\.new\b",
    r"\bos\.environ\b",
    r"\bgetenv\b",
    r"\bX-BAPI-SIGN\b",
    r"\bOK-ACCESS-KEY\b",
    r"\bapi_secret\b",
    r"\bprivate_key\b",
    r"\bseed_phrase\b",
    r"\bmnemonic\b",
)

#: Endpoints that only a transacting client would call.
TRANSACTING_ENDPOINTS = (
    "/v5/order/create",
    "/v5/asset/withdraw",
    "/api/v5/trade/order",
    "/api/v5/asset/withdrawal",
    "hashpower/order",
    "/main/api/v2/hashpower/order",
)

#: Cloud hashing surfaces. Control plane, storage and monitoring uses would be
#: permissible later; hashing never is, and none of these appear at all.
CLOUD_HASHING_PATTERNS = (
    r"amazonaws\.com",
    r"aliyuncs\.com",
    r"\bboto3\b",
    r"\bec2\b",
    r"run_instances",
)


#: The scanner is the one module excluded, because it necessarily contains
#: every string it searches for. Exactly one exclusion, named here so it is
#: visible rather than implied, and asserted by a test.
SELF_EXCLUDED_MODULE = "quant_trade.v9.safety"


def _v9_modules() -> dict[str, Any]:
    """Import every module in the V9 package, so nothing hides from the scan."""
    import quant_trade.v9 as package

    modules: dict[str, Any] = {}
    for info in pkgutil.iter_modules(package.__path__):
        name = f"quant_trade.v9.{info.name}"
        if name == SELF_EXCLUDED_MODULE:
            continue
        modules[name] = importlib.import_module(name)
    return modules


def scan_execution_boundary() -> dict[str, Any]:
    """Look for any code path that could transact. Report what was found."""
    findings: list[dict[str, str]] = []
    scanned: list[str] = []

    for name, module in sorted(_v9_modules().items()):
        scanned.append(name)
        for forbidden in FORBIDDEN_NAMES:
            if hasattr(module, forbidden):
                findings.append({"module": name, "kind": "transacting_name", "detail": forbidden})
        try:
            source = inspect.getsource(module)
        except (OSError, TypeError):  # pragma: no cover - compiled or missing source
            continue
        for pattern in CREDENTIAL_PATTERNS:
            if re.search(pattern, source):
                findings.append({"module": name, "kind": "credential_handling", "detail": pattern})
        for endpoint in TRANSACTING_ENDPOINTS:
            if endpoint in source:
                findings.append(
                    {"module": name, "kind": "transacting_endpoint", "detail": endpoint}
                )
        for pattern in CLOUD_HASHING_PATTERNS:
            if re.search(pattern, source, re.IGNORECASE):
                findings.append({"module": name, "kind": "cloud_hashing", "detail": pattern})

    return {
        "modules_scanned": scanned,
        "excluded": [SELF_EXCLUDED_MODULE],
        "findings": findings,
        "clean": not findings,
    }


def safety_report() -> dict[str, Any]:
    """The boundary, plus the result of checking the package against it."""
    scan = scan_execution_boundary()
    return {
        "artifact": "V9_SAFETY_REPORT",
        "schema_version": 1,
        "execution_flags": dict(sorted(EXECUTION_FLAGS.items())),
        "flags_are_configurable": False,
        "modules_scanned": len(scan["modules_scanned"]),
        "findings": scan["findings"],
        "clean": scan["clean"],
        "counters": {
            "real_orders_submitted": 0,
            "hashrate_purchased": 0,
            "deposits": 0,
            "withdrawals": 0,
            "transactions_signed": 0,
            "cloud_resources_created": 0,
            "funds_moved_usd": 0.0,
            "secrets_requested": 0,
            "secrets_stored": 0,
        },
        "cloud_provider_policy": (
            "AWS and Alibaba may later serve as control plane, collector, "
            "storage, monitoring or paper host. Hashing on them is prohibited, "
            "and no V9 module references either provider at all."
        ),
        "credential_policy": (
            "No V9 module reads a credential, signs a request, or accepts a "
            "secret as an argument. Fee-schedule import takes response bytes "
            "the operator captured themselves."
        ),
        "note": (
            "These flags are not read at runtime to decide anything — there is "
            "no branch they could enable. They are a written statement of a "
            "boundary that the scan above verifies against the code."
        ),
    }


__all__ = [
    "CLOUD_HASHING_PATTERNS",
    "CREDENTIAL_PATTERNS",
    "EXECUTION_FLAGS",
    "FORBIDDEN_NAMES",
    "SELF_EXCLUDED_MODULE",
    "TRANSACTING_ENDPOINTS",
    "safety_report",
    "scan_execution_boundary",
]
