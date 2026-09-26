"""``TOTALS_VS_ROWS`` and ``SUMMARY_IDENTITIES``: fixtures, one-cell edits,
localised labels, scoping rules and determinism. Offline: the fixtures are
the only input and the importer's own warnings feed the first check."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quant_trade.audit import importers
from quant_trade.audit.forensics import families, rows
from quant_trade.audit.forensics.checks import Context, totals
from quant_trade.audit.forensics.header import read_header
from quant_trade.audit.forensics.results import (
    DECLARED,
    EVIDENCE,
    MEASURED,
    NOT_MEASURED,
    STATUS_CLEAN,
    RawOutcome,
)
from quant_trade.audit.forensics.review import REASONS, review
from quant_trade.audit.forensics.rows import RawTable

FIXTURES = Path(__file__).parent / "fixtures" / "audit_imports"
HTML_FIXTURES = ("mt4_statement.htm", "mt5_history.html", "mt5_tester.html", "mt4_tester.htm")
CSV_FIXTURES = ("tradingview_g1.csv", "tradingview_g3b.csv", "ninjatrader.csv")
FORBIDDEN = ("12345678", "Demo Trader", "Synthetic", "FixtureEA")


def _bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _edit(name: str, old: str, new: str) -> bytes:
    data = _bytes(name)
    assert data.count(old.encode("utf-8")) == 1, (name, old)
    return data.replace(old.encode("utf-8"), new.encode("utf-8"))


def _load(data: bytes, name: str) -> tuple[RawTable, Context]:
    source_format = importers.detect_format(data, name)
    table = rows.load(data, source_format)
    report = importers.import_report(data, name)
    ctx = Context(
        family=table.family,
        header=read_header(table),
        imported_warnings=tuple(report.warnings),
        currency=report.currency or "",
    )
    return table, ctx


def _figures(outcome: RawOutcome) -> dict[str, tuple[str, str]]:
    found: dict[str, tuple[str, str]] = {}
    for key, value, evidence in outcome.figures:
        found.setdefault(key, (value, evidence))
    return found


def _assert_well_formed(outcome: RawOutcome) -> None:
    for figure in outcome.figures:
        assert len(figure) == 3
        assert all(isinstance(item, str) for item in figure)
        assert figure[2] in EVIDENCE
    serialised = json.dumps(outcome.figures)
    for needle in FORBIDDEN:
        assert needle not in serialised
    assert list(outcome.examples) == sorted(outcome.examples)
    assert len(outcome.examples) <= 5


# ---------------------------------------------------------------------------
# TOTALS_VS_ROWS
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", HTML_FIXTURES + CSV_FIXTURES)
def test_totals_fixture_is_clean(name: str) -> None:
    table, ctx = _load(_bytes(name), name)
    outcome = totals.run_TOTALS_VS_ROWS(table, ctx)
    _assert_well_formed(outcome)
    assert not outcome.not_measured
    assert outcome.hits == 0
    figures = _figures(outcome)
    assert figures["n_rows"] == (str(len(ctx.imported_warnings)), MEASURED)
    assert figures["n_hits"] == ("0", MEASURED)
    assert figures["importer_balance_breaks"] == ("0", MEASURED)
    assert "what_code" not in figures
    assert outcome == totals.run_TOTALS_VS_ROWS(table, ctx)


@pytest.mark.parametrize(
    ("name", "old", "new", "code", "declared", "measured", "example"),
    [
        (
            "mt5_tester.html",
            "<td nowrap><b>5</b></td>",
            "<td nowrap><b>6</b></td>",
            "closing_deals_vs_total_trades",
            "6.00",
            "5.00",
            15,
        ),
        (
            "mt4_statement.htm",
            "<b>-194.30</b></td>\n</tr>",
            "<b>-194.00</b></td>\n</tr>",
            "closed_trade_pnl",
            "-194.00",
            "-194.30",
            11,
        ),
        (
            "mt4_tester.htm",
            "<td align=right>95.10</td>",
            "<td align=right>96.10</td>",
            "net_profit",
            "96.10",
            "95.10",
            7,
        ),
        (
            "mt5_history.html",
            "<td nowrap><b>9.40</b></td>",
            "<td nowrap><b>9.90</b></td>",
            "net_profit_of_closed_positions",
            "9.90",
            "9.40",
            26,
        ),
        (
            "tradingview_g1.csv",
            "5342.75,3,-41.10,-0.26,8.50,0.01",
            "5342.75,3,-41.10,-0.26,9.50,0.01",
            "other",
            "9.50",
            "8.50",
            4,
        ),
        (
            "ninjatrader.csv",
            "($410.16),($102.74)",
            "($410.16),($112.74)",
            "other",
            "-112.74",
            "-102.74",
            2,
        ),
    ],
)
def test_totals_one_cell_edit_is_a_hit(
    name: str, old: str, new: str, code: str, declared: str, measured: str, example: int
) -> None:
    table, ctx = _load(_edit(name, old, new), name)
    outcome = totals.run_TOTALS_VS_ROWS(table, ctx)
    _assert_well_formed(outcome)
    assert not outcome.not_measured
    assert outcome.hits == 1
    assert outcome.examples == (example,)
    figures = _figures(outcome)
    assert figures["n_hits"] == ("1", MEASURED)
    assert figures["what_code"] == (code, MEASURED)
    assert figures["declared"] == (declared, DECLARED)
    assert figures["measured"] == (measured, MEASURED)
    assert outcome == totals.run_TOTALS_VS_ROWS(table, ctx)


def test_totals_reports_the_importers_balance_breaks_without_a_hit() -> None:
    data = _edit("mt5_history.html", "<td nowrap>990.37</td>", "<td nowrap>991.37</td>")
    table, ctx = _load(data, "mt5_history.html")
    assert any("Balance cell(s)" in line for line in ctx.imported_warnings)
    outcome = totals.run_TOTALS_VS_ROWS(table, ctx)
    assert outcome.hits == 0
    assert not outcome.not_measured
    assert _figures(outcome)["importer_balance_breaks"] == ("2", MEASURED)


def test_totals_parses_prefixed_lines_with_thousands_commas() -> None:
    table, ctx = _load(_bytes("mt5_tester.html"), "mt5_tester.html")
    lines = (
        "report: net profit: the report states 1,234.50 but the rows add up to 1,230.00",
        "report: balance drawdown maximal: the report states -12.00 but the rows add up to 0.00",
        "report: 3 Balance cell(s) do not equal the previous balance plus the row's money; "
        "the reported Balance was kept",
        "the file's times carry no timezone (platform or server time); they were read as UTC",
    )
    outcome = totals.run_TOTALS_VS_ROWS(table, Context(ctx.family, ctx.header, lines))
    _assert_well_formed(outcome)
    assert outcome.hits == 2
    figures = _figures(outcome)
    assert figures["n_rows"] == ("4", MEASURED)
    assert figures["n_hits"] == ("2", MEASURED)
    assert figures["what_code"] == ("net_profit", MEASURED)
    assert figures["declared"] == ("1234.50", DECLARED)
    assert figures["measured"] == ("1230.00", MEASURED)
    assert figures["what_code_2"] == ("balance_drawdown_maximal", MEASURED)
    assert figures["declared_2"] == ("-12.00", DECLARED)
    assert figures["measured_2"] == ("0.00", MEASURED)
    assert figures["importer_balance_breaks"] == ("3", MEASURED)
    # The example is the row of the "Total Net Profit" label; the drawdown
    # label is not printed by this fixture, so it adds no example.
    assert outcome.examples == (14,)


def test_totals_what_code_slugs() -> None:
    assert totals._what_code("closed trade P/L") == "closed_trade_pnl"
    assert totals._what_code("closing deals vs Total Trades") == "closing_deals_vs_total_trades"
    assert totals._what_code("close rows vs Total trades") == "close_rows_vs_total_trades"
    assert totals._what_code("net profit of closed positions") == "net_profit_of_closed_positions"
    assert totals._what_code("balance drawdown maximal") == "balance_drawdown_maximal"
    assert totals._what_code("cumulative P&L") == "other"
    assert totals._what_code("Cum. net profit") == "other"


def test_totals_several_accounts_is_not_measured() -> None:
    table, ctx = _load(_bytes("ninjatrader.csv"), "ninjatrader.csv")
    lines = (
        "the file holds 3 accounts; only the one with the most closed trades (7) was read",
        "Cum. net profit: the report states 1,035.61 but the rows add up to 438.11",
    )
    outcome = totals.run_TOTALS_VS_ROWS(table, Context(ctx.family, ctx.header, lines))
    _assert_well_formed(outcome)
    assert outcome.not_measured
    assert outcome.reason == "several_accounts"
    assert outcome.hits == 0
    figures = _figures(outcome)
    assert figures["n_hits"] == ("0", MEASURED)
    assert figures["accounts"] == ("3", MEASURED)
    assert figures["declared"] == ("1035.61", DECLARED)


def test_totals_several_accounts_from_the_file_itself() -> None:
    data = _bytes("ninjatrader.csv")
    lines = data.decode("utf-8").splitlines()
    extra = lines[1].replace(",Backtest,", ",Other,").replace("$307.42,$307.42", "$1.00,$308.42")
    data = "\n".join([*lines, extra]).encode("utf-8")
    table, ctx = _load(data, "ninjatrader.csv")
    assert any("the file holds 2 accounts" in line for line in ctx.imported_warnings)
    outcome = totals.run_TOTALS_VS_ROWS(table, ctx)
    assert outcome.not_measured
    assert outcome.reason == "several_accounts"


def test_totals_no_declared_totals_when_the_summary_lacks_the_label() -> None:
    data = _edit("mt5_history.html", "Total Net Profit:", "Net Result:")
    table, ctx = _load(data, "mt5_history.html")
    outcome = totals.run_TOTALS_VS_ROWS(table, ctx)
    assert outcome.not_measured
    assert outcome.reason == "no_declared_totals"
    assert _figures(outcome)["n_rows"][1] == MEASURED


def test_totals_no_declared_totals_for_a_format_without_comparisons() -> None:
    table = RawTable("other", families.OTHER, (), (), "none", "none", "none", 0, False)
    outcome = totals.run_TOTALS_VS_ROWS(table, Context(families.OTHER, read_header(table)))
    assert outcome.not_measured
    assert outcome.reason == "no_declared_totals"
    assert outcome.reason in REASONS


def test_totals_without_any_warning_is_clean_when_the_format_declares_totals() -> None:
    table, ctx = _load(_bytes("mt4_statement.htm"), "mt4_statement.htm")
    outcome = totals.run_TOTALS_VS_ROWS(table, Context(ctx.family, ctx.header, ()))
    assert not outcome.not_measured
    assert outcome.hits == 0
    assert _figures(outcome)["n_rows"] == ("0", MEASURED)


# ---------------------------------------------------------------------------
# SUMMARY_IDENTITIES
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "evaluated", "measured", "skipped"),
    [
        (
            "mt4_statement.htm",
            "3",
            {
                "balance_flows_pnl": ("8805.70", "8805.70"),
                "equity_balance_floating": ("9305.70", "9305.70"),
                "closed_pnl_summary": ("-194.30", "-194.30"),
            },
            ("net_profit_gross", "trades_short_long", "trades_profit_loss", "profit_factor_gross"),
        ),
        (
            "mt5_history.html",
            "2",
            {
                "net_profit_gross": ("9.40", "9.40"),
                "equity_balance_floating": ("909.40", "909.40"),
            },
            ("free_margin_equity_margin", "trades_short_long", "profit_factor_gross"),
        ),
        (
            "mt5_tester.html",
            "1",
            {"trades_short_long": ("5", "5")},
            ("net_profit_gross", "trades_profit_loss", "profit_factor_gross"),
        ),
        (
            "mt4_tester.htm",
            "2",
            {"net_profit_gross": ("95.10", "95.10"), "trades_short_long": ("4", "4")},
            ("trades_profit_loss", "profit_factor_gross"),
        ),
    ],
)
def test_identities_fixture_is_clean(
    name: str, evaluated: str, measured: dict[str, tuple[str, str]], skipped: tuple[str, ...]
) -> None:
    table, ctx = _load(_bytes(name), name)
    outcome = totals.run_SUMMARY_IDENTITIES(table, ctx)
    _assert_well_formed(outcome)
    assert not outcome.not_measured
    assert outcome.hits == 0
    assert outcome.examples == ()
    figures = _figures(outcome)
    assert figures["n_hits"] == ("0", MEASURED)
    assert figures["n_identities"] == (evaluated, MEASURED)
    assert figures["n_rows"] == (str(sum(1 for row in table.rows if row.kind == "label")), MEASURED)
    for code, (left, right) in measured.items():
        assert figures[code] == ("0", MEASURED)
        assert figures[f"{code}_left"] == (left, DECLARED)
        assert figures[f"{code}_right"] == (right, DECLARED)
    for code in skipped:
        assert figures[code] == ("no_declared_totals", NOT_MEASURED)
    assert outcome == totals.run_SUMMARY_IDENTITIES(table, ctx)


@pytest.mark.parametrize(
    ("name", "old", "new", "codes", "examples"),
    [
        (
            "mt4_statement.htm",
            "<b>-194.30</b></td><td colspan=4><b>Floating P/L:</b>",
            "<b>-194.40</b></td><td colspan=4><b>Floating P/L:</b>",
            ("balance_flows_pnl", "closed_pnl_summary"),
            (17, 18),
        ),
        (
            "mt4_statement.htm",
            "<b>Equity:</b></td><td class=mspt><b>9 305.70</b>",
            "<b>Equity:</b></td><td class=mspt><b>9 306.70</b>",
            ("equity_balance_floating",),
            (18,),
        ),
        (
            "mt5_history.html",
            "<td nowrap><b>18.68</b></td>",
            "<td nowrap><b>18.86</b></td>",
            ("net_profit_gross",),
            (26,),
        ),
        (
            "mt5_tester.html",
            "<b>2 (50.00%)</b>",
            "<b>3 (50.00%)</b>",
            ("trades_short_long",),
            (15,),
        ),
        (
            "mt4_tester.htm",
            "<td align=right>-30.40</td>",
            "<td align=right>-30.00</td>",
            ("net_profit_gross",),
            (7,),
        ),
    ],
)
def test_identities_one_cell_edit_is_a_hit(
    name: str, old: str, new: str, codes: tuple[str, ...], examples: tuple[int, ...]
) -> None:
    table, ctx = _load(_edit(name, old, new), name)
    outcome = totals.run_SUMMARY_IDENTITIES(table, ctx)
    _assert_well_formed(outcome)
    assert not outcome.not_measured
    assert outcome.hits == len(codes)
    assert outcome.examples == examples
    figures = _figures(outcome)
    assert figures["n_hits"] == (str(len(codes)), MEASURED)
    for code in codes:
        assert figures[code] == ("1", MEASURED)
        assert figures[f"{code}_left"][1] == DECLARED
        assert figures[f"{code}_right"][1] == DECLARED
        assert figures[f"{code}_left"][0] != figures[f"{code}_right"][0]
    assert outcome == totals.run_SUMMARY_IDENTITIES(table, ctx)


def test_identities_period_export_skips_the_balance_and_equity_identities() -> None:
    # The deposit dated after the first trade's open: not a full-history export.
    data = _edit("mt4_statement.htm", "2024.03.01 08:00:00", "2024.03.04 09:30:00")
    table, ctx = _load(data, "mt4_statement.htm")
    outcome = totals.run_SUMMARY_IDENTITIES(table, ctx)
    assert outcome.hits == 0
    figures = _figures(outcome)
    assert figures["balance_flows_pnl"] == ("no_qualifying_row", NOT_MEASURED)
    assert figures["equity_balance_floating"] == ("no_qualifying_row", NOT_MEASURED)
    assert figures["closed_pnl_summary"] == ("0", MEASURED)
    assert figures["n_identities"] == ("1", MEASURED)


def test_identities_withdrawal_first_is_not_a_full_history() -> None:
    # The importer refuses this file (the account is wiped), so the context
    # is built from the table alone: the check needs no warnings here.
    data = _edit("mt4_statement.htm", "<td class=mspt>10 000.00</td>", "<td class=mspt>-10.00</td>")
    table = rows.load(data, importers.detect_format(data, "mt4_statement.htm"))
    ctx = Context(table.family, read_header(table))
    figures = _figures(totals.run_SUMMARY_IDENTITIES(table, ctx))
    assert figures["balance_flows_pnl"] == ("no_qualifying_row", NOT_MEASURED)


_MT4_DETAILS = (
    "<tr align=right><td colspan=2><b>Gross Profit:</b></td><td colspan=2 class=mspt>"
    "<b>200.00</b></td><td colspan=4><b>Gross Loss:</b></td><td class=mspt><b>370.00</b></td>"
    "<td colspan=3><b>Total Net Profit:</b></td><td colspan=2 class=mspt><b>-170.00</b></td></tr>\n"
    "<tr align=right><td colspan=2><b>Total Trades:</b></td><td colspan=2 class=mspt><b>3</b></td>"
    "<td colspan=4><b>Short Positions (won %):</b></td><td class=mspt><b>2 (0.00%)</b></td>"
    "<td colspan=3><b>Long Positions (won %):</b></td><td colspan=2 class=mspt>"
    "<b>1 (100.00%)</b></td></tr>\n"
    "<tr align=right><td colspan=2><b>Profit Trades (% of total):</b></td><td colspan=2 class=mspt>"
    "<b>1 (33.33%)</b></td><td colspan=4><b>Loss trades (% of total):</b></td><td class=mspt>"
    "<b>2 (66.67%)</b></td><td colspan=3><b>Profit Factor:</b></td><td colspan=2 class=mspt>"
    "<b>0.54</b></td></tr>\n"
)


def test_identities_mt4_statement_details_block_with_unsigned_gross_loss() -> None:
    tail = "</table>\n</div></body></html>"
    data = _edit("mt4_statement.htm", tail, _MT4_DETAILS + tail)
    table, ctx = _load(data, "mt4_statement.htm")
    outcome = totals.run_SUMMARY_IDENTITIES(table, ctx)
    _assert_well_formed(outcome)
    assert outcome.hits == 0
    figures = _figures(outcome)
    assert figures["n_identities"] == ("7", MEASURED)
    assert figures["net_profit_gross_right"] == ("-170.00", DECLARED)
    assert figures["trades_short_long_right"] == ("3", DECLARED)
    assert figures["trades_profit_loss_right"] == ("3", DECLARED)
    assert figures["profit_factor_gross_left"] == ("0.54", DECLARED)
    assert figures["profit_factor_gross_right"] == ("0.541", DECLARED)
    edited = data.replace(b"<b>0.54</b>", b"<b>0.64</b>")
    table, ctx = _load(edited, "mt4_statement.htm")
    outcome = totals.run_SUMMARY_IDENTITIES(table, ctx)
    assert outcome.hits == 1
    assert _figures(outcome)["profit_factor_gross"] == ("1", MEASURED)


_MT5_RESULTS = (
    '   <tr align="right"><td nowrap colspan="3">Gross Profit:</td><td nowrap><b>82.50</b></td>'
    '<td nowrap colspan="3">Gross Loss:</td><td nowrap><b>-19.45</b></td>'
    '<td nowrap colspan="3">Profit Factor:</td><td nowrap colspan="2"><b>4.24</b></td></tr>\n'
    '   <tr align="right"><td nowrap colspan="3">Profit Trades (% of total):</td>'
    '<td nowrap><b>3 (60.00%)</b></td><td nowrap colspan="3">Loss Trades (% of total):</td>'
    "<td nowrap><b>2 (40.00%)</b></td></tr>\n"
)
_MT5_TOTAL_DEALS = '   <tr align="right"><td nowrap colspan="3">Total Deals:</td>'


def test_identities_mt5_tester_results_block() -> None:
    data = _edit("mt5_tester.html", _MT5_TOTAL_DEALS, _MT5_RESULTS + _MT5_TOTAL_DEALS)
    table, ctx = _load(data, "mt5_tester.html")
    outcome = totals.run_SUMMARY_IDENTITIES(table, ctx)
    _assert_well_formed(outcome)
    assert outcome.hits == 0
    figures = _figures(outcome)
    assert figures["n_identities"] == ("4", MEASURED)
    assert figures["net_profit_gross_right"] == ("63.05", DECLARED)
    assert figures["trades_profit_loss_right"] == ("5", DECLARED)
    assert figures["profit_factor_gross_right"] == ("4.242", DECLARED)
    # A profit factor off by a cent is a hit; the ratio tolerance is 0.005.
    table, ctx = _load(data.replace(b"<b>4.24</b>", b"<b>4.25</b>"), "mt5_tester.html")
    outcome = totals.run_SUMMARY_IDENTITIES(table, ctx)
    assert outcome.hits == 1
    assert outcome.examples == (16,)
    # No losses: the profit factor identity cannot run.
    flat = data.replace(b"<b>82.50</b>", b"<b>63.05</b>").replace(b"<b>-19.45</b>", b"<b>0.00</b>")
    table, ctx = _load(flat, "mt5_tester.html")
    figures = _figures(totals.run_SUMMARY_IDENTITIES(table, ctx))
    assert figures["profit_factor_gross"] == ("no_qualifying_row", NOT_MEASURED)
    assert figures["net_profit_gross"] == ("0", MEASURED)


def test_identities_mt5_history_free_margin_only_when_nothing_floats() -> None:
    margin = _edit(
        "mt5_history.html",
        '<td colspan="3">Margin Level:</td><td colspan="2"><b>0.00%</b></td>',
        '<td colspan="3">Margin:</td><td colspan="2"><b>100.00</b></td>',
    )
    table, ctx = _load(margin, "mt5_history.html")
    outcome = totals.run_SUMMARY_IDENTITIES(table, ctx)
    figures = _figures(outcome)
    assert outcome.hits == 1
    assert figures["free_margin_equity_margin"] == ("1", MEASURED)
    assert figures["free_margin_equity_margin_right"] == ("809.40", DECLARED)
    assert outcome.examples == (22,)
    floating = margin.replace(
        b'<td colspan="3">Floating P/L:</td><td colspan="2"><b>0.00</b></td>',
        b'<td colspan="3">Floating P/L:</td><td colspan="2"><b>-1.50</b></td>',
    )
    assert floating != margin
    table, ctx = _load(floating, "mt5_history.html")
    figures = _figures(totals.run_SUMMARY_IDENTITIES(table, ctx))
    assert figures["free_margin_equity_margin"] == ("no_qualifying_row", NOT_MEASURED)
    assert figures["equity_balance_floating"] == ("1", MEASURED)


def test_identities_localised_labels_are_read_through_the_alias_tables() -> None:
    data = (
        _bytes("mt5_history.html")
        .replace(b"Total Net Profit:", b"Beneficio Neto:")
        .replace(b"Gross Profit:", b"Beneficio Bruto:")
        .replace(b"Gross Loss:", "Pérdidas Brutas:".encode())
        .replace(b"Equity:", b"Majetek:")
    )
    table, ctx = _load(data, "mt5_history.html")
    outcome = totals.run_SUMMARY_IDENTITIES(table, ctx)
    assert outcome.hits == 0
    figures = _figures(outcome)
    assert figures["n_identities"] == ("2", MEASURED)
    assert figures["net_profit_gross"] == ("0", MEASURED)
    assert figures["equity_balance_floating"] == ("0", MEASURED)
    unknown = data.replace(b"Beneficio Bruto:", b"Ganancia:")
    table, ctx = _load(unknown, "mt5_history.html")
    figures = _figures(totals.run_SUMMARY_IDENTITIES(table, ctx))
    assert figures["net_profit_gross"] == ("no_declared_totals", NOT_MEASURED)
    assert figures["n_identities"] == ("1", MEASURED)


def test_identities_mt4_tester_portuguese_labels() -> None:
    data = (
        _bytes("mt4_tester.htm")
        .replace(b"Total net profit", "Lucro líquido total".encode())
        .replace(b"Gross profit", b"Lucro Bruto")
        .replace(b"Gross loss", b"Perda Bruta")
        .replace(b"Total trades", "Total de negociações".encode())
        .replace(b"Short positions (won %)", "Posições Vendidas (ganhos %)".encode())
        .replace(b"Long positions (won %)", "Posições Compradas (ganhos %)".encode())
    )
    table, ctx = _load(data, "mt4_tester.htm")
    outcome = totals.run_SUMMARY_IDENTITIES(table, ctx)
    assert outcome.hits == 0
    assert _figures(outcome)["n_identities"] == ("2", MEASURED)


def test_identities_alias_tables_are_per_family_and_collision_free() -> None:
    # "Всего сделок" is MT4's Total trades but MT5's Total Deals: never pooled.
    assert totals._ALIASES[families.MT4_TESTER]["всего сделок"] == "total_trades"
    assert "всего сделок" not in totals._ALIASES[families.MT5_TESTER]
    assert totals._ALIASES[families.MT5_TESTER]["всего трейдов"] == "total_trades"
    assert totals._ALIASES[families.MT5_HISTORY] == totals._ALIASES[families.MT5_TESTER]
    for family, table in (
        (families.MT5_TESTER, totals._MT5_EXTRA_ALIASES),
        (families.MT4_TESTER, totals._MT4_TESTER_EXTRA_ALIASES),
    ):
        aliases = totals._ALIASES[family]
        for english, names in table.items():
            assert english.lower() in aliases
            for name in names:
                assert aliases[name.lower()] == aliases[english.lower()]
    # The importers' tables carry the English keys the identities rely on.
    for english in ("Total Net Profit", "Total Trades", "Profit Factor", "Equity", "Floating P/L"):
        assert english in importers._MT5_LABEL_ALIASES
    for english in ("Total net profit", "Total trades", "Profit factor"):
        assert english in importers._MT4_LABEL_ALIASES


@pytest.mark.parametrize("name", CSV_FIXTURES)
def test_identities_csv_families_are_not_covered(name: str) -> None:
    table, ctx = _load(_bytes(name), name)
    outcome = totals.run_SUMMARY_IDENTITIES(table, ctx)
    assert outcome.not_measured
    assert outcome.reason == "format_not_covered"


def test_identities_no_declared_totals_when_no_identity_can_run() -> None:
    data = (
        _bytes("mt4_tester.htm")
        .replace(b"Gross profit", b"Bruto")
        .replace(b"Short positions (won %)", b"Curtas")
    )
    table, ctx = _load(data, "mt4_tester.htm")
    outcome = totals.run_SUMMARY_IDENTITIES(table, ctx)
    assert outcome.not_measured
    assert outcome.reason == "no_declared_totals"
    assert _figures(outcome)["n_identities"] == ("0", MEASURED)


@pytest.mark.parametrize("name", HTML_FIXTURES)
def test_review_runs_both_checks_clean(name: str) -> None:
    data = _bytes(name)
    source_format = importers.detect_format(data, name)
    report = importers.import_report(data, name)
    result = review(data, source_format=source_format, imported_warnings=report.warnings)
    for check_id in ("TOTALS_VS_ROWS", "SUMMARY_IDENTITIES"):
        check = result.check(check_id)
        assert check.status == STATUS_CLEAN
        assert check.applies
        assert check.figure("n_hits") == "0"
    serialised = json.dumps(result.as_dict())
    for needle in FORBIDDEN:
        assert needle not in serialised
