"""The execution boundary, verified against the package rather than asserted.

These tests are the reason the boundary is trustworthy: they import every V9
module and look for the names, credential handling, endpoints and cloud
surfaces a transacting code path would need.
"""

from __future__ import annotations

import importlib
import inspect
import json
import pkgutil

import pytest
from typer.testing import CliRunner

from quant_trade.cli import app
from quant_trade.v9.safety import (
    CLOUD_HASHING_PATTERNS,
    CREDENTIAL_PATTERNS,
    EXECUTION_FLAGS,
    FORBIDDEN_NAMES,
    SELF_EXCLUDED_MODULE,
    TRANSACTING_ENDPOINTS,
    safety_report,
    scan_execution_boundary,
)


def v9_module_names() -> list[str]:
    import quant_trade.v9 as package

    return sorted(f"quant_trade.v9.{i.name}" for i in pkgutil.iter_modules(package.__path__))


def test_the_package_has_no_transacting_code_path() -> None:
    scan = scan_execution_boundary()
    assert scan["clean"], scan["findings"]
    assert len(scan["modules_scanned"]) >= 15


def test_exactly_one_module_is_excluded_from_the_scan() -> None:
    """The scanner contains every string it looks for; nothing else may hide."""
    scan = scan_execution_boundary()
    assert scan["excluded"] == [SELF_EXCLUDED_MODULE]
    assert SELF_EXCLUDED_MODULE not in scan["modules_scanned"]


def test_every_execution_flag_is_off() -> None:
    assert EXECUTION_FLAGS["LIVE_ORDER_SUBMISSION"] == "DISABLED"
    assert EXECUTION_FLAGS["LIVE_BROKER_EXECUTION"] == "DISABLED"
    assert EXECUTION_FLAGS["MINING_PURCHASE_EXECUTION"] == "DISABLED"
    assert EXECUTION_FLAGS["DEPOSIT_EXECUTION"] == "DISABLED"
    assert EXECUTION_FLAGS["WITHDRAWAL_EXECUTION"] == "DISABLED"
    assert EXECUTION_FLAGS["WALLET_SIGNING"] == "DISABLED"
    assert EXECUTION_FLAGS["AWS_ALIBABA_HASHING"] == "PROHIBITED"
    assert EXECUTION_FLAGS["CLOUD_RESOURCE_CREATION"] == "DISABLED"
    assert EXECUTION_FLAGS["EXTERNAL_SPEND"] == "DISABLED"
    assert safety_report()["flags_are_configurable"] is False


@pytest.mark.parametrize("module_name", v9_module_names())
def test_no_module_defines_a_transacting_verb(module_name: str) -> None:
    if module_name == SELF_EXCLUDED_MODULE:
        pytest.skip("the scanner names every verb it searches for")
    module = importlib.import_module(module_name)
    for name in FORBIDDEN_NAMES:
        assert not hasattr(module, name), f"{module_name} defines {name}"


@pytest.mark.parametrize("module_name", v9_module_names())
def test_no_module_handles_a_credential(module_name: str) -> None:
    import re

    if module_name == SELF_EXCLUDED_MODULE:
        pytest.skip("the scanner names every pattern it searches for")
    source = inspect.getsource(importlib.import_module(module_name))
    for pattern in CREDENTIAL_PATTERNS:
        assert not re.search(pattern, source), f"{module_name} matches {pattern}"


@pytest.mark.parametrize("module_name", v9_module_names())
def test_no_module_names_a_transacting_endpoint(module_name: str) -> None:
    if module_name == SELF_EXCLUDED_MODULE:
        pytest.skip("the scanner names every endpoint it searches for")
    source = inspect.getsource(importlib.import_module(module_name))
    for endpoint in TRANSACTING_ENDPOINTS:
        assert endpoint not in source, f"{module_name} references {endpoint}"


@pytest.mark.parametrize("module_name", v9_module_names())
def test_no_module_reaches_a_cloud_hashing_surface(module_name: str) -> None:
    import re

    if module_name == SELF_EXCLUDED_MODULE:
        pytest.skip("the scanner names every provider it searches for")
    source = inspect.getsource(importlib.import_module(module_name))
    for pattern in CLOUD_HASHING_PATTERNS:
        assert not re.search(pattern, source, re.IGNORECASE), f"{module_name} matches {pattern}"


def test_the_scanner_actually_finds_something_when_there_is_something() -> None:
    """A scan that cannot fail proves nothing, so make it fail on purpose."""
    import re

    planted = "def submit_live_order(): pass\nimport hmac\n'/v5/order/create'\n"
    assert any(re.search(p, planted) for p in CREDENTIAL_PATTERNS)
    assert any(e in planted for e in TRANSACTING_ENDPOINTS)
    assert any(n in planted for n in FORBIDDEN_NAMES)


def test_no_v9_cli_command_transacts() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["v9", "--help"])
    assert result.exit_code == 0
    output = result.stdout.lower()
    for verb in ("buy", "purchase", "deposit", "withdraw", "sign", "transfer", "launch"):
        assert f" {verb}-" not in output
        assert f"{verb} hashrate" not in output


def test_the_safety_report_counters_are_all_zero() -> None:
    counters = safety_report()["counters"]
    assert counters["real_orders_submitted"] == 0
    assert counters["hashrate_purchased"] == 0
    assert counters["deposits"] == 0
    assert counters["withdrawals"] == 0
    assert counters["transactions_signed"] == 0
    assert counters["cloud_resources_created"] == 0
    assert counters["funds_moved_usd"] == 0.0
    assert counters["secrets_requested"] == 0
    assert counters["secrets_stored"] == 0


def test_safety_report_command_runs() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["v9", "safety-report"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["clean"] is True
    assert payload["execution_flags"]["WITHDRAWAL_EXECUTION"] == "DISABLED"


def test_cost_import_never_asks_for_a_secret() -> None:
    """It takes bytes the operator captured; it cannot reach a key itself."""
    from quant_trade.v9 import cli as v9_cli

    source = inspect.getsource(v9_cli)
    for pattern in ("api_key", "api_secret", "passphrase=", "getenv", "os.environ"):
        assert pattern not in source
    # And the documented never-send list is advice, not a parameter.
    from quant_trade.v9.cost_evidence import operator_capture_instructions

    instructions = operator_capture_instructions("bybit")
    assert instructions["never_send"]
    assert "signing_code" not in instructions


@pytest.mark.parametrize(
    ("venue", "payload", "extra"),
    [
        (
            "bybit",
            {
                "retCode": 0,
                "result": {
                    "list": [
                        {"symbol": "BTCUSDT", "makerFeeRate": "0.0001", "takerFeeRate": "0.00055"}
                    ]
                },
            },
            [],
        ),
        (
            "okx",
            {"code": "0", "data": [{"instType": "SPOT", "maker": "-0.00008", "taker": "-0.0001"}]},
            ["--leg", "spot"],
        ),
    ],
)
def test_cost_import_records_bytes_and_stores_no_secret(
    tmp_path, venue: str, payload: dict, extra: list[str]
) -> None:
    """The command runs end to end and the bundle traces back to the bytes."""
    raw = tmp_path / f"{venue}.json"
    raw.write_text(json.dumps(payload), encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "v9",
            "cost-import",
            "--venue",
            venue,
            "--raw",
            str(raw),
            "--effective-from",
            "2026-07-28T00:00:00Z",
            "--expires-at",
            "2026-08-28T00:00:00Z",
            "--out-dir",
            str(tmp_path),
            *extra,
        ],
    )
    assert result.exit_code == 0, result.stdout
    reported = json.loads(result.stdout)
    assert reported["venue"] == venue
    assert reported["secrets_stored"] == 0
    assert reported["weakest_evidence_class"] == "REAL_ACCOUNT_SPECIFIC"

    written = json.loads((tmp_path / f"cost_bundle_{venue}.json").read_text(encoding="utf-8"))
    from quant_trade.evidence.canonical_json import sha256_of_bytes

    digest = sha256_of_bytes(raw.read_bytes())
    assert all(s["raw_sha256"] == digest for s in written["schedules"])
    # Nothing resembling a credential reached the artifact.
    text = json.dumps(written).lower()
    for pattern in ("secret", "passphrase", "signature", "x-bapi-sign", "ok-access-key"):
        assert pattern not in text


def test_the_paper_engine_cannot_be_handed_a_return() -> None:
    """A caller supplies market ticks; equity is derived, never supplied."""
    from quant_trade.v9.paper_session import PaperSession

    signature = inspect.signature(PaperSession.advance)
    assert list(signature.parameters) == ["self", "ticks"]
    for forbidden in ("cash_yield_daily", "pnl", "net_return", "equity_usd", "wall_clock"):
        assert forbidden not in signature.parameters
