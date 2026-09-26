"""``review``: every check, every time, in order; one status rule; nothing
from the file in the result."""

from __future__ import annotations

import hashlib
import importlib
from pathlib import Path

import pytest

from quant_trade.audit import importers
from quant_trade.audit.forensics import (
    CHECK_ORDER,
    METHOD_VERSION,
    SIGNAL_CAPABLE,
    STATUS_CLEAN,
    STATUS_INFO,
    STATUS_NOT_MEASURED,
    STATUS_SIGNAL,
    STATUSES,
    calibration,
    decide,
    review,
)
from quant_trade.audit.forensics.results import EVIDENCE, RawOutcome
from quant_trade.evidence.canonical_json import canonical_dumps

review_module = importlib.import_module("quant_trade.audit.forensics.review")
FIXTURES = Path(__file__).parent / "fixtures" / "audit_imports"
PRIVATE_TEXT = (
    "12345678",
    "Demo Trader",
    "Synthetic",
    "SyntheticBroker-Demo",
    "FixtureEA",
    "Dmitry",
    "Impact",
)
ALL_FIXTURES = sorted(path.name for path in FIXTURES.iterdir() if path.suffix != ".xml")


def _review(name: str):
    data = (FIXTURES / name).read_bytes()
    return review(data, source_format=importers.detect_format(data))


@pytest.mark.parametrize("name", ALL_FIXTURES)
def test_every_check_is_present_in_order_with_valid_shape(name: str) -> None:
    result = _review(name)
    assert result.method_version == METHOD_VERSION
    assert tuple(check.id for check in result.checks) == CHECK_ORDER
    for check in result.checks:
        assert check.status in STATUSES, check.id
        assert check.applies == (check.status != STATUS_NOT_MEASURED)
        if check.status == STATUS_NOT_MEASURED:
            assert check.reason in review_module.REASONS, (check.id, check.reason)
        else:
            assert check.reason == ""
        for key, value, evidence in check.figures:
            assert isinstance(key, str) and key == key.lower(), (check.id, key)
            assert isinstance(value, str), (check.id, key)
            assert evidence in EVIDENCE, (check.id, key)
        assert list(check.examples) == sorted(check.examples) and len(check.examples) <= 5
        assert all(isinstance(index, int) and index >= 0 for index in check.examples)
    assert sum(value for _name, value in result.counts) == len(CHECK_ORDER)
    payload = canonical_dumps(result.as_dict())
    assert "NaN" not in payload and "Infinity" not in payload


@pytest.mark.parametrize("name", ALL_FIXTURES)
def test_review_is_deterministic(name: str) -> None:
    first = canonical_dumps(_review(name).as_dict())
    second = canonical_dumps(_review(name).as_dict())
    assert first == second


@pytest.mark.parametrize("name", ALL_FIXTURES)
def test_result_holds_no_text_from_the_file(name: str) -> None:
    payload = canonical_dumps(_review(name).as_dict())
    for private in PRIVATE_TEXT:
        assert private not in payload, private
    # No float ever reaches the payload: values are strings, counts ints.
    for check in _review(name).checks:
        for _key, value, _evidence in check.figures:
            assert not isinstance(value, float)


def test_unaltered_fixtures_have_no_signal_or_hit() -> None:
    """The synthetic fixtures are consistent by construction: any hit on
    them is a bug in a check, not a finding."""
    descriptive = {"FILE_TRACE", "STATEMENT_PERIOD"}
    for name in ALL_FIXTURES:
        for check in _review(name).checks:
            assert check.status != STATUS_SIGNAL, (name, check.id)
            if check.id in descriptive:
                continue
            assert check.status in {STATUS_CLEAN, STATUS_NOT_MEASURED}, (
                name,
                check.id,
                check.status,
                check.figures,
                check.examples,
            )


def test_decide_applies_the_one_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    hit = RawOutcome(hits=1)
    none = RawOutcome(hits=0)
    skip = RawOutcome.skip("no_table")
    assert decide("BALANCE_CHAIN", "mt5_tester", skip) == STATUS_NOT_MEASURED
    assert decide("BALANCE_CHAIN", "mt5_tester", none) == STATUS_CLEAN
    assert decide("BALANCE_CHAIN", "mt5_tester", hit) == STATUS_INFO
    granted = calibration.Cell(n=24, n_reserved=8, unexplained=0, frozen="2026-10-01")
    monkeypatch.setitem(calibration.CALIBRATION, ("BALANCE_CHAIN", "mt5_tester"), granted)
    assert decide("BALANCE_CHAIN", "mt5_tester", hit) == STATUS_SIGNAL
    assert decide("BALANCE_CHAIN", "mt5_history", hit) == STATUS_INFO
    monkeypatch.setitem(calibration.THRESHOLDS, ("BALANCE_CHAIN", "mt5_tester"), 1)
    assert decide("BALANCE_CHAIN", "mt5_tester", hit) == STATUS_INFO
    assert decide("BALANCE_CHAIN", "mt5_tester", RawOutcome(hits=2)) == STATUS_SIGNAL
    # Descriptive checks never signal, whatever the table says.
    monkeypatch.setitem(calibration.CALIBRATION, ("FILE_TRACE", "mt5_tester"), granted)
    assert "FILE_TRACE" not in SIGNAL_CAPABLE
    assert decide("FILE_TRACE", "mt5_tester", hit) == STATUS_INFO
    # A cell short of twenty files, unexplained hits or no freeze date grants nothing.
    for cell in (
        calibration.Cell(n=19, n_reserved=6, unexplained=0, frozen="2026-10-01"),
        calibration.Cell(n=40, n_reserved=13, unexplained=1, frozen="2026-10-01"),
        calibration.Cell(n=40, n_reserved=13, unexplained=0, frozen=""),
    ):
        monkeypatch.setitem(calibration.CALIBRATION, ("BALANCE_CHAIN", "mt5_tester"), cell)
        assert decide("BALANCE_CHAIN", "mt5_tester", RawOutcome(hits=5)) == STATUS_INFO


def test_calibration_line_and_clopper_pearson() -> None:
    assert calibration.clopper_pearson_upper_pct(0, 8) == "36.9"
    assert calibration.clopper_pearson_upper_pct(0, 16) == "20.6"
    assert calibration.clopper_pearson_upper_pct(0, 20) == "16.8"
    assert calibration.clopper_pearson_upper_pct(0, 24) == "14.2"
    assert calibration.clopper_pearson_upper_pct(0, 40) == "8.8"
    assert calibration.clopper_pearson_upper_pct(0, 0) == "100.0"
    assert calibration.clopper_pearson_upper_pct(3, 3) == "100.0"
    # 1 of 20: the exact bound is 24.9 %; 2 of 40: 16.9 %.
    assert calibration.clopper_pearson_upper_pct(1, 20) == "24.9"
    assert calibration.clopper_pearson_upper_pct(2, 40) == "16.9"


def test_empty_calibration_table_is_shipped() -> None:
    """No cell is granted until a corpus run is frozen and reviewed."""
    assert all(not cell.granted for cell in calibration.CALIBRATION.values())


def test_truncated_table_skips_order_sensitive_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    from quant_trade.audit import schema

    monkeypatch.setattr(schema, "MAX_ROWS", 20)
    result = _review("mt5_tester.html")
    assert result.truncated is True
    for check in result.checks:
        if check.id in review_module.ORDER_SENSITIVE:
            assert check.status == STATUS_NOT_MEASURED and check.reason == "truncated", check.id


def test_report_format_errors_propagate() -> None:
    with pytest.raises(importers.ReportFormatError):
        review(b"", source_format=None)


def test_monthly_review_runs_without_rows() -> None:
    import pandas as pd

    from quant_trade.audit import factsheet

    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    frame = pd.DataFrame(
        [[2020, *[0.5 + 0.1 * i for i in range(12)]], [2021, *[-0.2 + 0.1 * i for i in range(12)]]],
        columns=["Year", *months],
    )
    grid = factsheet.monthly_grid(frame)
    assert grid is not None
    result = review(b"", source_format=None, monthly=grid)
    assert result.family == "monthly"
    assert tuple(check.id for check in result.checks) == CHECK_ORDER


def test_frozen_modules_are_pinned_to_the_method_version() -> None:
    """Changing a threshold or a calibration cell is changing the method."""
    package = Path(review_module.__file__).parent
    pins = {
        "forensics-1": (
            _sha(package / "thresholds.py"),
            _sha(package / "calibration.py"),
        ),
    }
    assert METHOD_VERSION in pins, "bump METHOD_VERSION and add its pins"
    assert pins[METHOD_VERSION] == (
        _sha(package / "thresholds.py"),
        _sha(package / "calibration.py"),
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
