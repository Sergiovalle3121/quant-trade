"""The forgery lab on the repo fixtures: every applicable seed is found by
one of its expected checks, the unaltered file is found by none, and the
lab is deterministic and offline."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from quant_trade.audit.forensics import CHECK_ORDER, families

sys.path.insert(0, str(Path(__file__).parent))

import forgery_lab as lab  # noqa: E402

FAMILIES = set(families.HTML_FAMILIES) | set(families.CSV_FAMILIES) | {families.MONTHLY}

#: Strings the fixtures carry that must never reach the lab's output.
_FIXTURE_MARKERS = ("12345678", "Demo Trader", "Synthetic", "FixtureEA")


@pytest.fixture(scope="module")
def results() -> dict[str, list[lab.SeedResult]]:
    return lab.run_fixtures()


def _applied(results: dict[str, list[lab.SeedResult]]) -> set[tuple[str, str]]:
    return {
        (name, item.seed_id) for name, items in results.items() for item in items if item.applied
    }


def test_seed_table_is_well_formed() -> None:
    assert len(set(lab.SEED_IDS)) == len(lab.SEEDS)
    for seed in lab.SEEDS + (lab.IDENTITY,):
        assert seed.families and set(seed.families) <= FAMILIES, seed.id
        assert set(seed.expected_checks) <= set(CHECK_ORDER), seed.id
        for family, checks in seed.overrides:
            assert family in seed.families, (seed.id, family)
            assert set(checks) <= set(CHECK_ORDER), (seed.id, family)
        assert seed.edit, seed.id


def test_every_applicable_seed_is_found_on_fixtures(
    results: dict[str, list[lab.SeedResult]],
) -> None:
    missed = [
        (name, item.seed_id, item.expected, item.found_by, item.note)
        for name, items in results.items()
        for item in items
        if item.applied and item.expected and not item.expected_found
    ]
    assert missed == []


def test_seeds_apply_on_fixtures(results: dict[str, list[lab.SeedResult]]) -> None:
    """Each seed is exercised on at least one fixture, and the pairs that
    apply are pinned so a selection rule cannot silently stop applying."""
    applied = _applied(results)
    for seed in lab.SEEDS:
        assert any(seed_id == seed.id for _name, seed_id in applied), seed.id
    expected_applied = {
        ("mt4_statement.htm", "delete_losing_row"),
        ("mt4_statement.htm", "summary_total_edit"),
        ("mt4_statement.htm", "move_to_open"),
        ("mt4_statement.htm", "sltp_fill_violation"),
        ("mt4_statement.htm", "header_date_backwards"),
        ("mt5_history.html", "fill_hidden_number"),
        ("mt5_history.html", "close_price_mirror"),
        ("mt5_history.html", "order_number_change"),
        ("mt5_tester.html", "deal_number_change"),
        ("mt5_tester.html", "sltp_fill_violation"),
        ("mt4_tester.htm", "swap_adjacent_rows"),
        ("tradingview_g3b.csv", "close_price_mirror"),
        ("tradingview_g1.csv", "profit_plus_cent"),
        ("ninjatrader.csv", "profit_sign_flip"),
        ("myfxbook.csv", "duplicate_new_ticket"),
        ("mql5_signal.csv", "close_time_weekend"),
        ("fxblue.csv", "drop_deposit"),
        ("monthly", "monthly_value"),
    }
    assert expected_applied <= applied


def test_unaltered_fixtures_are_not_found(results: dict[str, list[lab.SeedResult]]) -> None:
    for name, data in lab.fixture_files():
        fmt = lab.importers.detect_format(data)
        for item in lab.run_seeds(data, fmt, (lab.IDENTITY,)):
            assert item.applied and item.found_by == (), name
    for item in lab.run_seeds(b"", None, (lab.IDENTITY,), monthly=lab.monthly_sample()):
        assert item.applied and item.found_by == ()


def test_identity_edit_keeps_bytes() -> None:
    for name, data in lab.fixture_files():
        table = lab.rows.load(data, lab.importers.detect_format(data))
        assert lab.IDENTITY.apply(data, table) == data, name


def test_alterations_change_the_file() -> None:
    """A seed that applies returns different bytes that still load as the
    same family (the display:none seed is the documented exception: the
    reader ignores styles, so the table is the same)."""
    for name, data in lab.fixture_files():
        fmt = lab.importers.detect_format(data)
        table = lab.rows.load(data, fmt)
        for seed in lab.SEEDS:
            if table.family not in seed.families:
                continue
            altered = seed.apply(data, table)
            if altered is None:
                continue
            assert altered != data, (name, seed.id)
            assert lab.rows.load(altered, fmt).family == table.family, (name, seed.id)


def test_monthly_seed_found_by_digits() -> None:
    items = lab.run_seeds(b"", None, monthly=lab.monthly_sample())
    by_id = {item.seed_id: item for item in items}
    assert "MONTHLY_DIGITS" in by_id["monthly_value"].found_by


def test_deterministic(results: dict[str, list[lab.SeedResult]]) -> None:
    again = lab.run_fixtures()
    assert lab.fixtures_report(again) == lab.fixtures_report(results)


def test_report_carries_no_fixture_text(results: dict[str, list[lab.SeedResult]]) -> None:
    text = json.dumps(lab.fixtures_report(results))
    for marker in _FIXTURE_MARKERS:
        assert marker not in text


def test_cli_fixtures(tmp_path: Path) -> None:
    out = tmp_path / "fixtures.json"
    completed = subprocess.run(
        [sys.executable, str(Path(lab.__file__)), "--fixtures", "--out", str(out)],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(Path(__file__).parent.parent),
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(out.read_text())
    assert set(report) == {name for name, _data in lab.fixture_files()} | {"monthly"}


def test_csv_editor_round_trips() -> None:
    for name in ("myfxbook.csv", "mql5_signal.csv", "fxblue.csv"):
        data = lab.SAMPLES[name]
        table = lab.rows.load(data, lab.importers.detect_format(data))
        assert lab._Csv(data, table).rebuild({}) == data, name


def test_time_rewrite_keeps_layout() -> None:
    from datetime import datetime

    parsed = datetime(2023, 12, 21, 2, 55)
    target = datetime(2023, 12, 23, 15, 0)
    assert lab._rewrite_time("12/21/2023 02:55", parsed, target) == "12/23/2023 15:00"
    assert lab._rewrite_time("21/12/2023 02:55:00", parsed, target) == "23/12/2023 15:00:00"
    assert lab._rewrite_time("2023.12.21 02:55:00", parsed, target) == "2023.12.23 15:00:00"
    assert lab._rewrite_time("12/21/2023 2:55 AM", parsed, target) == "12/23/2023 3:00 PM"
    assert lab._rewrite_time("21 Dec 2023", parsed, target) is None


def test_money_restyle() -> None:
    from decimal import Decimal

    assert lab._restyle_money("49.6", Decimal("49.61")) == "49.61"
    assert lab._restyle_money("-50.70", Decimal("50.70")) == "50.70"
    assert lab._restyle_money("(41.10)", Decimal("-42.10")) == "(42.10)"
    assert lab._restyle_money("$1,000.00", Decimal("1100")) == "$1100.00"
    assert lab._restyle_money("-10,50", Decimal("-11.5")) == "-11,50"
