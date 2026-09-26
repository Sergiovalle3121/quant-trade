"""``TV_INVARIANTS`` and ``NT_INVARIANTS``: the delimited trade lists of
TradingView and NinjaTrader (spec §3.21, §3.22)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from quant_trade.audit import importers
from quant_trade.audit.forensics import families, rows
from quant_trade.audit.forensics.checks import Context, platforms
from quant_trade.audit.forensics.header import read_header
from quant_trade.audit.forensics.results import EVIDENCE, MEASURED, RawOutcome
from quant_trade.audit.forensics.review import REASONS, review
from quant_trade.evidence.canonical_json import canonical_dumps

FIXTURES = Path(__file__).parent / "fixtures" / "audit_imports"
PRIVATE_TEXT = ("12345678", "Demo Trader", "Synthetic Broker", "SyntheticBroker-Demo", "FixtureEA")
NUMBER = re.compile(r"^-?\d+(\.\d+)?$")

G3_HEADER = (
    "Trade number,Type,Date and time,Signal,Price USD,Size (qty),Size (value),Net PnL USD,"
    "Return %,Commission USD,Favorable excursion USD,Favorable excursion %,"
    "Adverse excursion USD,Adverse excursion %,Cumulative PnL USD,Cumulative PnL %,"
    "Duration (bars)"
)
#: Five closed trades in the G3 shape (exit row first, as TradingView prints them).
G3_FIVE = [
    "1,Exit long,2026-03-02 14:00,TP,5321.5,2,10591,49.6,0.47,2.4,60,0.57,-18,-0.17,49.6,0.05,6",
    "1,Entry long,2026-03-02 08:00,Long,5295.5,2,10591,49.6,0.47,2.4,60,0.57,-18,-0.17,49.6,0.05,6",
    "2,Exit short,2026-03-03 13:00,Close,5342.75,3,15990.75,-41.1,-0.26,3.6,12.75,0.08,-45,"
    "-0.28,8.5,0.01,3",
    "2,Entry short,2026-03-03 10:00,Short,5330.25,3,15990.75,-41.1,-0.26,3.6,12.75,0.08,-45,"
    "-0.28,8.5,0.01,3",
    "3,Exit long,2026-03-04 15:00,Close,5361,1,5350,10.4,0.19,0.6,14,0.26,-3,-0.06,18.9,0.02,6",
    "3,Entry long,2026-03-04 09:00,Long,5350,1,5350,10.4,0.19,0.6,14,0.26,-3,-0.06,18.9,0.02,6",
    "4,Exit long,2026-03-05 12:00,Close,5310,2,10600,20,0.19,1.2,25,0.24,-4,-0.04,38.9,0.04,3",
    "4,Entry long,2026-03-05 09:00,Long,5300,2,10600,20,0.19,1.2,25,0.24,-4,-0.04,38.9,0.04,3",
    "5,Exit long,2026-03-06 11:00,Close,5395,1,5400,-5,-0.09,0.6,2,0.04,-6,-0.11,33.9,0.03,2",
    "5,Entry long,2026-03-06 09:00,Long,5400,1,5400,-5,-0.09,0.6,2,0.04,-6,-0.11,33.9,0.03,2",
]
#: Two overlapping trades (pyramiding) and one after them; trade 1 closes while
#: trade 2 is open, so its cumulative carries trade 2's open P&L (12, not 10).
G3_PYRAMID = [
    "1,Exit long,2026-03-02 12:00,Close,110,1,100,10,10.00,0,10,10.00,0,0.00,12,0.12,4",
    "1,Entry long,2026-03-02 08:00,Long,100,1,100,10,10.00,0,10,10.00,0,0.00,12,0.12,4",
    "2,Exit long,2026-03-02 14:00,Close,105,1,100,5,5.00,0,10,10.00,0,0.00,15,0.15,4",
    "2,Entry long,2026-03-02 10:00,Long,100,1,100,5,5.00,0,10,10.00,0,0.00,15,0.15,4",
    "3,Exit long,2026-03-03 10:00,Close,101,1,100,1,1.00,0,1,1.00,0,0.00,16,0.16,2",
    "3,Entry long,2026-03-03 08:00,Long,100,1,100,1,1.00,0,1,1.00,0,0.00,16,0.16,2",
]
NT_EU_HEADER = (
    "Trade number;Instrument;Account;Strategy;Market pos.;Qty;Entry price;Exit price;"
    "Entry time;Exit time;Entry name;Exit name;Profit;Cum. net profit;Commission;MAE;MFE;"
    "ETD;Bars;"
)
NT_EU_ROWS = [
    "1;ES SEP25;Sim;;Long;1;6387,50;6383,50;13/9/2025 12:18:21;13/9/2025 12:35:29;Entry;"
    "Stop1;-$ 200,00;-$ 200,00;$ 0,00;$ 200,00;$ 175,00;$ 375,00;0;",
    "2;ES SEP25;Sim;;Short;1;6445,00;6449,00;14/9/2025 16:46:10;14/9/2025 16:50:00;Entry;"
    "Stop1;-$ 200,00;-$ 400,00;$ 0,00;$ 200,00;$ 37,50;$ 237,50;0;",
]


def _lines(name: str) -> list[str]:
    return (FIXTURES / name).read_text(encoding="utf-8").splitlines()


def _table(lines: list[str], source_format: str | None = None) -> rows.RawTable:
    data = ("\n".join(lines) + "\n").encode("utf-8")
    return rows.load(data, source_format or importers.detect_format(data))


def _ctx(table: rows.RawTable) -> Context:
    return Context(family=table.family, header=read_header(table))


def _tv(lines: list[str]) -> RawOutcome:
    table = _table(lines, importers.TRADINGVIEW_CSV)
    return platforms.run_TV_INVARIANTS(table, _ctx(table))


def _nt(lines: list[str]) -> RawOutcome:
    table = _table(lines, importers.NINJATRADER_CSV)
    return platforms.run_NT_INVARIANTS(table, _ctx(table))


def _figures(outcome: RawOutcome) -> dict[str, str]:
    return {key: value for key, value, _evidence in outcome.figures}


def _assert_shape(outcome: RawOutcome) -> None:
    keys = [key for key, _value, _evidence in outcome.figures]
    assert len(keys) == len(set(keys))
    assert {"n_rows", "n_hits"} <= set(keys)
    for key, value, evidence in outcome.figures:
        assert key == key.lower() and isinstance(value, str) and NUMBER.match(value), (key, value)
        assert evidence in EVIDENCE and evidence == MEASURED, key
    assert list(outcome.examples) == sorted(outcome.examples) and len(outcome.examples) <= 5
    assert outcome.hits == int(_figures(outcome)["n_hits"])
    payload = canonical_dumps(
        {"f": [list(f) for f in outcome.figures], "e": list(outcome.examples)}
    )
    for private in PRIVATE_TEXT:
        assert private not in payload


# ---------------------------------------------------------------------------
# TradingView
# ---------------------------------------------------------------------------


def test_tv_fixtures_are_clean() -> None:
    g3b = _tv(_lines("tradingview_g3b.csv"))
    _assert_shape(g3b)
    assert g3b.hits == 0 and g3b.examples == () and not g3b.not_measured
    figures = _figures(g3b)
    assert figures["n_rows"] == "6" and figures["n_trades"] == "3"
    assert figures["n_open"] == "1" and figures["n_closed"] == "2"
    assert figures["size_multiplier"] == "1" and figures["size_value_examined"] == "1"
    assert figures["return_pct_examined"] == "1" and figures["cumulative_examined"] == "1"
    assert figures["time_examined"] == "2" and figures["last_trade_excluded"] == "1"
    g1 = _tv(_lines("tradingview_g1.csv"))
    _assert_shape(g1)
    assert g1.hits == 0 and g1.examples == ()
    figures = _figures(g1)
    assert figures["n_trades"] == "2" and figures["n_open"] == "0"
    assert figures["size_value_examined"] == "0" and figures["return_pct_examined"] == "0"
    assert figures["cumulative_examined"] == "1" and figures["time_examined"] == "2"
    assert "size_multiplier" not in figures


def test_tv_is_deterministic() -> None:
    first = _tv(_lines("tradingview_g3b.csv"))
    second = _tv(_lines("tradingview_g3b.csv"))
    assert canonical_dumps([list(f) for f in first.figures]) == canonical_dumps(
        [list(f) for f in second.figures]
    )
    assert first == second


def test_tv_deleted_trade_leaves_a_numbering_gap() -> None:
    lines = _lines("tradingview_g3b.csv")
    cut = [line for line in lines if not line.startswith("2,")]
    outcome = _tv(cut)
    _assert_shape(outcome)
    figures = _figures(outcome)
    assert figures["numbering_gaps"] == "1" and figures["n_trades"] == "2"
    assert outcome.hits == 1 and outcome.examples == (3,)


def test_tv_edited_cell_breaks_the_pair_and_the_identities() -> None:
    lines = _lines("tradingview_g3b.csv")
    assert lines[1].startswith("1,Exit long")
    lines[1] = lines[1].replace(",49.6,0.47,", ",59.6,0.47,", 1)
    outcome = _tv(lines)
    _assert_shape(outcome)
    figures = _figures(outcome)
    assert figures["pair_values"] == "1"
    assert figures["cumulative"] == "1" and figures["return_pct"] == "1"
    assert outcome.hits == 1 and outcome.examples == (1,)


def test_tv_exit_before_entry() -> None:
    lines = _lines("tradingview_g3b.csv")
    lines[1] = lines[1].replace("2026-03-02 14:00", "2026-03-02 07:00", 1)
    outcome = _tv(lines)
    _assert_shape(outcome)
    figures = _figures(outcome)
    assert figures["exit_before_entry"] == "1" and figures["time_examined"] == "2"
    assert figures["cumulative_examined"] == "0" and figures["last_trade_excluded"] == "0"
    assert outcome.hits == 1 and outcome.examples == (1,)


def test_tv_third_row_for_one_trade_is_a_shape_hit() -> None:
    lines = _lines("tradingview_g3b.csv")
    lines.append(lines[3])
    outcome = _tv(lines)
    _assert_shape(outcome)
    assert _figures(outcome)["pair_shape"] == "1"
    assert outcome.hits == 1 and outcome.examples == (3,)


def test_tv_size_value_against_one_multiplier_per_file() -> None:
    clean = _tv([G3_HEADER, *G3_FIVE])
    _assert_shape(clean)
    assert clean.hits == 0
    figures = _figures(clean)
    assert figures["n_closed"] == "5" and figures["size_multiplier"] == "1"
    assert figures["size_value_examined"] == "4" and figures["return_pct_examined"] == "4"
    assert figures["cumulative_examined"] == "4"
    edited = list(G3_FIVE)
    edited[2] = edited[2].replace(",15990.75,", ",15900.75,", 1)
    edited[3] = edited[3].replace(",15990.75,", ",15900.75,", 1)
    outcome = _tv([G3_HEADER, *edited])
    figures = _figures(outcome)
    assert figures["size_value"] == "1" and figures["pair_values"] == "0"
    assert figures["size_multiplier"] == "1"
    assert outcome.hits == 1 and outcome.examples == (3,)


def test_tv_cumulative_is_read_at_flat_moments_only() -> None:
    clean = _tv([G3_HEADER, *G3_PYRAMID])
    _assert_shape(clean)
    assert clean.hits == 0
    figures = _figures(clean)
    assert figures["cumulative_examined"] == "1" and figures["last_trade_excluded"] == "1"
    edited = list(G3_PYRAMID)
    edited[2] = edited[2].replace(",15,0.15,", ",14,0.15,", 1)
    edited[3] = edited[3].replace(",15,0.15,", ",14,0.15,", 1)
    outcome = _tv([G3_HEADER, *edited])
    assert _figures(outcome)["cumulative"] == "1"
    assert outcome.hits == 1 and outcome.examples == (3,)


def test_tv_open_last_trade_is_not_a_hit() -> None:
    lines = _lines("tradingview_g1.csv")
    one_row = lines[:1] + ["3,Entry Long,Long,2024-11-06 10:00,5350.00,1,,,,,,,,"] + lines[1:]
    outcome = _tv(one_row)
    _assert_shape(outcome)
    assert outcome.hits == 0
    assert _figures(outcome)["n_open"] == "1" and _figures(outcome)["n_closed"] == "2"
    two_rows = (
        lines[:1]
        + ["3,Exit Long,Open,,,,,,,,,,,", "3,Entry Long,Long,2024-11-06 10:00,5350.00,1,,,,,,,,"]
        + lines[1:]
    )
    outcome = _tv(two_rows)
    assert outcome.hits == 0 and _figures(outcome)["n_open"] == "1"


def test_tv_cut_head_is_a_numbering_start_hit() -> None:
    lines = _lines("tradingview_g1.csv")
    outcome = _tv([line for line in lines if not line.startswith("1,")])
    _assert_shape(outcome)
    assert _figures(outcome)["numbering_start"] == "1"
    assert outcome.hits == 1 and outcome.examples == (1,)


def test_tv_german_header_reads_by_position() -> None:
    lines = [
        "Trade #,Typ,Datum und Uhrzeit,Signal,Preis USD,Größe (Menge),Größe (Wert),"
        "G&V netto USD,G&V netto %,Positive Exkursion USD,Positive Exkursion %,"
        "Negative Exkursion USD,Negative Exkursion %,Kumulativer G&V USD,Kumulativer G&V %",
        "1,Short-Ausstieg,2025-03-14 14:40,S178 SL,19518.1,25,487642.5,-310,-0.06,0,0.00,-310,"
        "-0.06,-310,-0.31",
        "1,Short-Einstieg,2025-03-14 14:33,Short_178,19505.7,25,487642.5,-310,-0.06,0,0.00,"
        "-310,-0.06,-310,-0.31",
        "2,Short-Ausstieg,2025-03-14 14:50,S254 SL,19547.9,25,488415,-282.5,-0.06,0,0.00,"
        "-282.5,-0.06,-592.5,-0.59",
        "2,Short-Einstieg,2025-03-14 14:41,Short_254,19536.6,25,488415,-282.5,-0.06,0,0.00,"
        "-282.5,-0.06,-592.5,-0.59",
    ]
    outcome = _tv(lines)
    _assert_shape(outcome)
    assert outcome.hits == 0
    figures = _figures(outcome)
    assert figures["n_trades"] == "2" and figures["size_value_examined"] == "1"
    assert figures["return_pct_examined"] == "0" and figures["time_examined"] == "2"


def test_tv_return_pct_needs_one_currency_and_an_itemised_commission() -> None:
    cross = [G3_HEADER.replace("Net PnL USD", "Net PnL GBP"), *G3_FIVE]
    assert _figures(_tv(cross))["return_pct_examined"] == "0"
    no_commission = [
        ",".join(cell for cell in G3_HEADER.split(",") if cell != "Commission USD"),
        *(",".join(cell for i, cell in enumerate(row.split(",")) if i != 9) for row in G3_FIVE),
    ]
    outcome = _tv(no_commission)
    assert outcome.hits == 0 and _figures(outcome)["return_pct_examined"] == "0"


def test_tv_return_pct_band_covers_the_entry_share_of_the_commission() -> None:
    """Whichever share of the commission TradingView charges the entry, a
    return computed over the entry value is inside the band."""
    lines = [G3_HEADER, *G3_FIVE]
    lines[1] = lines[1].replace(",49.6,0.47,2.4,", ",49.6,0.47,400,", 1)
    lines[2] = lines[2].replace(",49.6,0.47,2.4,", ",49.6,0.47,400,", 1)
    outcome = _tv(lines)
    assert outcome.hits == 0 and _figures(outcome)["return_pct_examined"] == "4"


def test_tv_not_measured_reasons() -> None:
    mt4 = _table(_lines("mt4_statement.htm"))
    outcome = platforms.run_TV_INVARIANTS(mt4, _ctx(mt4))
    assert outcome.not_measured and outcome.reason == "format_not_covered"
    expected = {
        "no_table": ["Initial capital,All USD", "Net profit,59.17"],
        "no_column": ["Trade #,Type,Signal", "1,Entry Long,Long"],
        "no_qualifying_row": [G3_HEADER],
    }
    for reason, lines in expected.items():
        outcome = _tv(lines)
        assert outcome.not_measured and outcome.reason == reason
        assert reason in REASONS


def test_tv_ambiguous_dates_leave_times_unexamined() -> None:
    lines = [G3_HEADER] + [
        row.replace("2026-03-02", "02/03/2026")
        .replace("2026-03-03", "03/03/2026")
        .replace("2026-03-04", "04/03/2026")
        .replace("2026-03-05", "05/03/2026")
        .replace("2026-03-06", "06/03/2026")
        for row in G3_FIVE
    ]
    outcome = _tv(lines)
    _assert_shape(outcome)
    figures = _figures(outcome)
    assert figures["time_examined"] == "0" and figures["cumulative_examined"] == "0"
    assert figures["size_value_examined"] == "5" and outcome.hits == 0


# ---------------------------------------------------------------------------
# NinjaTrader
# ---------------------------------------------------------------------------


def test_nt_fixture_is_clean() -> None:
    outcome = _nt(_lines("ninjatrader.csv"))
    _assert_shape(outcome)
    assert outcome.hits == 0 and outcome.examples == () and not outcome.not_measured
    figures = _figures(outcome)
    assert figures["n_rows"] == "2" and figures["n_trades"] == "2"
    assert figures["cumulative_examined"] == "2" and figures["etd_examined"] == "2"
    assert figures["time_examined"] == "2"
    assert _nt(_lines("ninjatrader.csv")) == outcome


def test_nt_edited_profit_breaks_cumulative_and_etd() -> None:
    lines = _lines("ninjatrader.csv")
    lines[2] = lines[2].replace("($410.16)", "($400.16)", 1)
    outcome = _nt(lines)
    _assert_shape(outcome)
    figures = _figures(outcome)
    assert figures["cumulative"] == "1" and figures["etd"] == "1"
    assert outcome.hits == 1 and outcome.examples == (2,)


def test_nt_deleted_first_row() -> None:
    lines = _lines("ninjatrader.csv")
    del lines[1]
    outcome = _nt(lines)
    _assert_shape(outcome)
    figures = _figures(outcome)
    assert figures["numbering_start"] == "1" and figures["cumulative"] == "1"
    assert figures["numbering_gaps"] == "0"
    assert outcome.hits == 1 and outcome.examples == (1,)


def test_nt_duplicated_row_and_gap() -> None:
    lines = _lines("ninjatrader.csv")
    outcome = _nt(lines + [lines[2]])
    _assert_shape(outcome)
    assert _figures(outcome)["numbering_duplicates"] == "1"
    assert outcome.hits == 1 and outcome.examples == (3,)
    gap = list(lines)
    gap[2] = gap[2].replace("2,ES 03-26", "4,ES 03-26", 1)
    outcome = _nt(gap)
    assert _figures(outcome)["numbering_gaps"] == "1" and outcome.examples == (2,)


def test_nt_exit_before_entry() -> None:
    lines = _lines("ninjatrader.csv")
    lines[1] = lines[1].replace("1/6/2026 10:05:00 AM", "1/6/2026 9:05:00 AM", 1)
    outcome = _nt(lines)
    _assert_shape(outcome)
    assert _figures(outcome)["exit_before_entry"] == "1"
    assert outcome.hits == 1 and outcome.examples == (1,)


def test_nt_eu_locale_export_is_clean() -> None:
    outcome = _nt([NT_EU_HEADER, *NT_EU_ROWS])
    _assert_shape(outcome)
    assert outcome.hits == 0
    figures = _figures(outcome)
    assert figures["cumulative_examined"] == "2" and figures["etd_examined"] == "2"
    assert figures["time_examined"] == "2"


def test_nt_not_measured_reasons() -> None:
    lines = _lines("ninjatrader.csv")
    points = [
        lines[0],
        lines[1].replace("$307.42,$307.42", "6.25,6.25", 1),
        lines[2].replace("($410.16),($102.74)", "-8.00,-1.75", 1),
    ]
    assert _nt(points).reason == "no_qualifying_row"
    assert _nt([lines[0]]).reason == "no_qualifying_row"
    assert _nt(["Trade number,Instrument", "1,ES 03-26"]).reason == "no_column"
    tv = _table(_lines("tradingview_g1.csv"))
    outcome = platforms.run_NT_INVARIANTS(tv, _ctx(tv))
    assert outcome.not_measured and outcome.reason == "format_not_covered"
    for reason in ("no_qualifying_row", "no_column", "format_not_covered"):
        assert reason in REASONS


def test_nt_several_accounts_share_one_grid() -> None:
    lines = _lines("ninjatrader.csv")
    lines[2] = lines[2].replace(",Backtest,", ",Other,", 1)
    outcome = _nt(lines)
    _assert_shape(outcome)
    assert not outcome.not_measured and outcome.hits == 0
    figures = _figures(outcome)
    assert figures["n_accounts"] == "2" and figures["cumulative_examined"] == "2"


# ---------------------------------------------------------------------------
# Through review()
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "tv_status", "nt_status"),
    [
        ("tradingview_g1.csv", "CLEAN", "NOT_MEASURED"),
        ("tradingview_g3b.csv", "CLEAN", "NOT_MEASURED"),
        ("ninjatrader.csv", "NOT_MEASURED", "CLEAN"),
        ("mt4_statement.htm", "NOT_MEASURED", "NOT_MEASURED"),
    ],
)
def test_review_statuses(name: str, tv_status: str, nt_status: str) -> None:
    data = (FIXTURES / name).read_bytes()
    result = review(data, source_format=importers.detect_format(data))
    assert result.check("TV_INVARIANTS").status == tv_status
    assert result.check("NT_INVARIANTS").status == nt_status
    payload = canonical_dumps(result.as_dict())
    for private in PRIVATE_TEXT:
        assert private not in payload


def test_review_hits_are_info_by_design() -> None:
    lines = _lines("tradingview_g3b.csv")
    cut = "\n".join(line for line in lines if not line.startswith("2,")).encode()
    result = review(cut, source_format=importers.TRADINGVIEW_CSV)
    check = result.check("TV_INVARIANTS")
    assert check.status == "INFO" and check.examples == (3,)
    assert result.family == families.TRADINGVIEW
    lines = _lines("ninjatrader.csv")
    lines[2] = lines[2].replace("($410.16)", "($400.16)", 1)
    result = review("\n".join(lines).encode(), source_format=importers.NINJATRADER_CSV)
    assert result.check("NT_INVARIANTS").status == "INFO"
