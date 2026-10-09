"""Costs in the trader's units: pips per side of each pair traded and money per
lot and side, beside the basis points the costs section measures. Offline."""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from quant_trade.audit.engine import (
    PER_LOT_MIXED,
    PER_LOT_NOTE,
    PER_LOT_NOTE_FEES,
    PER_LOT_NOTE_FEES_PAIRS,
    PER_LOT_NOTE_PAIRS,
    PER_LOT_ONLY_METATRADER,
    PIPS_BY_SYMBOL_NOTE,
    PIPS_NO_METAL_SIZE,
    PIPS_OTHERS_NOTE,
    _costs,
    _stress,
    _symbol_code,
    fx_pair,
    run_audit,
)
from quant_trade.audit.guard import find_claims
from quant_trade.audit.i18n import localize, untranslated
from quant_trade.audit.plan import _costs_step
from quant_trade.audit.report import (
    KEY_LABELS,
    LABELS,
    _challenge_ladder_html,
    _challenge_ladder_label,
    _kpi_evidence,
    _kpi_list,
    render_html,
)
from quant_trade.audit.sample import (
    _sample_report,
    synthetic_live_statement,
    synthetic_mt5_report,
)
from quant_trade.audit.schema import AuditResult, DeclaredMetadata, build_inputs

LOCALES = ("es", "en", "pt")
#: One round trip per row: symbol, side, lots, entry, exit and the money per
#: price unit of one lot (EURUSD 100,000; USDJPY 700 in this USD account, a
#: fixed figure so the size the importer infers is exact; XAUUSD 100 oz).
TRADES: tuple[tuple[str, str, float, float, float, float], ...] = (
    ("EURUSD", "buy", 1.0, 1.10000, 1.10200, 100_000.0),
    ("USDJPY", "buy", 1.0, 150.000, 150.500, 700.0),
    ("XAUUSD", "buy", 0.1, 2000.00, 2010.00, 100.0),
    ("EURUSD", "sell", 0.5, 1.10500, 1.10300, 100_000.0),
    ("USDJPY", "sell", 0.5, 151.000, 150.600, 700.0),
    ("EURUSD", "buy", 0.2, 1.09000, 1.08900, 100_000.0),
    ("XAUUSD", "sell", 0.2, 2020.00, 2025.00, 100.0),
    ("USDJPY", "buy", 0.3, 149.000, 148.800, 700.0),
    ("EURUSD", "sell", 1.0, 1.08000, 1.08100, 100_000.0),
)
#: The same history without the metal: two currency pairs only.
PAIRS = tuple(row for row in TRADES if row[0] != "XAUUSD")
#: Exchange prefixes, a pair and a metal behind them, and two symbols with no
#: pip size (a peso pair and an index): USDMXN 5,800 USD per peso, US30 1 USD.
PREFIXED: tuple[tuple[str, str, float, float, float, float], ...] = (
    ("OANDA:XAUUSD", "buy", 0.1, 2000.00, 2010.00, 100.0),
    ("FX:EURUSD", "buy", 1.0, 1.10000, 1.10200, 100_000.0),
    ("USDMXN", "buy", 1.0, 17.0000, 17.0500, 5_800.0),
    ("FX:EURUSD", "sell", 0.5, 1.10500, 1.10300, 100_000.0),
    ("US30", "buy", 1.0, 38_000.0, 38_100.0, 1.0),
    ("USDMXN", "sell", 1.0, 17.1000, 17.0000, 5_800.0),
    ("FX:EURUSD", "buy", 0.2, 1.09000, 1.08900, 100_000.0),
)
#: Gold alone, under two broker names of the same symbol.
GOLD: tuple[tuple[str, str, float, float, float, float], ...] = (
    ("XAUUSD", "buy", 0.1, 2000.00, 2010.00, 100.0),
    ("XAUUSD.r", "sell", 0.2, 2020.00, 2015.00, 100.0),
    ("XAUUSD", "buy", 0.1, 2030.00, 2028.00, 100.0),
)
#: Gold and silver: two metals, no pair (a lot of silver is 5,000 oz).
METALS = (*GOLD, ("XAGUSD", "buy", 0.1, 23.000, 23.100, 5_000.0))
#: Commission per lot on every deal (entry and exit), in USD.
COMMISSION_PER_LOT = 3.5
FIXTURES = Path(__file__).parent / "fixtures" / "audit_imports"
AND = {"es": "y", "en": "and", "pt": "e"}


def _profit(side: str, lots: float, entry: float, exit_price: float, per_unit: float) -> float:
    sign = 1.0 if side == "buy" else -1.0
    return round(sign * (exit_price - entry) * per_unit * lots, 2)


def _money(value: float) -> str:
    return f"{value:,.2f}".replace(",", " ")


def _mt5_report(trades: tuple[tuple[str, str, float, float, float, float], ...]) -> bytes:
    """An MT5 Strategy Tester HTML report (UTF-16 LE with BOM) with one round
    trip per business day, on the symbols and lots of ``trades``."""
    days = np.busday_offset("2024-01-02", np.arange(len(trades)), roll="forward")
    balance = 10_000.0
    rows = [
        "<tr><td>2024.01.01 00:00:00</td><td>1</td><td></td><td>balance</td><td></td><td></td>"
        "<td></td><td></td><td>0.00</td><td>0.00</td><td>10 000.00</td><td>10 000.00</td>"
        "<td></td></tr>"
    ]
    deal = 2
    for day, (symbol, side, lots, entry, exit_price, per_unit) in zip(days, trades, strict=True):
        stamp = str(day).replace("-", ".")
        commission = round(-COMMISSION_PER_LOT * lots, 2)
        balance += commission
        rows.append(
            f"<tr><td>{stamp} 09:00:00</td><td>{deal}</td><td>{symbol}</td><td>{side}</td>"
            f"<td>in</td><td>{lots}</td><td>{entry}</td><td>{deal}</td><td>{commission:.2f}</td>"
            f"<td>0.00</td><td>0.00</td><td>{_money(balance)}</td><td></td></tr>"
        )
        profit = _profit(side, lots, entry, exit_price, per_unit)
        balance += profit + commission
        close = "sell" if side == "buy" else "buy"
        rows.append(
            f"<tr><td>{stamp} 17:00:00</td><td>{deal + 1}</td><td>{symbol}</td><td>{close}</td>"
            f"<td>out</td><td>{lots}</td><td>{exit_price}</td><td>{deal + 1}</td>"
            f"<td>{commission:.2f}</td><td>0.00</td><td>{profit:.2f}</td>"
            f"<td>{_money(balance)}</td><td></td></tr>"
        )
        deal += 2
    header = (
        "<tr><td><b>Time</b></td><td><b>Deal</b></td><td><b>Symbol</b></td><td><b>Type</b></td>"
        "<td><b>Direction</b></td><td><b>Volume</b></td><td><b>Price</b></td>"
        "<td><b>Order</b></td><td><b>Commission</b></td><td><b>Swap</b></td>"
        "<td><b>Profit</b></td><td><b>Balance</b></td><td><b>Comment</b></td></tr>"
    )
    page = (
        "<html><head><title>Strategy Tester Report</title></head><body><table>"
        "<tr><td colspan='13'><b>Strategy Tester Report</b></td></tr>"
        "<tr><td colspan='3'>Expert:</td><td colspan='10'><b>SyntheticEA</b></td></tr>"
        "<tr><td colspan='3'>Currency:</td><td colspan='10'><b>USD</b></td></tr>"
        "<tr><td colspan='3'>Initial Deposit:</td><td colspan='10'><b>10 000.00</b></td></tr>"
        "</table><table><tr><th colspan='13'><b>Deals</b></th></tr>"
        + header
        + "".join(rows)
        + "</table></body></html>"
    )
    return b"\xff\xfe" + page.encode("utf-16-le")


def _audit(report: bytes, **declared: Any) -> AuditResult:
    inputs = build_inputs(
        None, DeclaredMetadata(**declared), report_bytes=report, report_filename="Report.html"
    )
    return run_audit(inputs, bootstrap_samples=50, risk_samples=50, challenge_samples=50)


@pytest.fixture(scope="module")
def mixed() -> dict[str, Any]:
    """Two pairs (one against the yen) and a metal, with a declared cost of 1 bp."""
    return _audit(_mt5_report(TRADES), cost_bps_per_side=1.0).model_dump(mode="json")


@pytest.fixture(scope="module")
def pairs() -> dict[str, Any]:
    """The two pairs without the metal, with a declared cost of 1 bp."""
    return _audit(_mt5_report(PAIRS), cost_bps_per_side=1.0).model_dump(mode="json")


def _by_hand_bps() -> float:
    """``break_even_bps`` by its closed form, from the rows written above."""
    gross = sum(_profit(s, lots, a, b, k) for _, s, lots, a, b, k in TRADES)
    fees = sum(2 * round(COMMISSION_PER_LOT * t[2], 2) for t in TRADES)
    notional = sum(lots * k * (a + b) for _, _, lots, a, b, k in TRADES)
    return 10_000.0 * (gross - fees) / notional


def test_pips_by_symbol_match_the_formula_for_two_pairs_and_a_metal(
    mixed: dict[str, Any],
) -> None:
    costs = mixed["costs"]
    bps = costs["break_even_bps"]["value"]
    assert bps == pytest.approx(_by_hand_bps(), rel=1e-9)
    # Several symbols: the one-pair keys stay out, the new block lists each one.
    assert "break_even_pips" not in costs and "pip_symbol" not in costs
    block = costs["pips_by_symbol"]
    assert block["note"] == PIPS_BY_SYMBOL_NOTE
    rows = {row["symbol"]: row for row in block["rows"]}
    # Most traded first: EURUSD 4, USDJPY 3, XAUUSD 2.
    assert [row["symbol"] for row in block["rows"]] == ["EURUSD", "USDJPY", "XAUUSD"]
    assert [row["trades"] for row in block["rows"]] == [4, 3, 2]
    medians = {"EURUSD": (1.09 + 1.10) / 2, "USDJPY": 150.0, "XAUUSD": (2000.0 + 2020.0) / 2}
    for symbol, price in medians.items():
        assert rows[symbol]["median_entry_price"]["value"] == pytest.approx(price)
    for symbol, pip in (("EURUSD", 0.0001), ("USDJPY", 0.01)):
        row = rows[symbol]
        price = medians[symbol]
        assert row["pip_size"] == pip
        assert row["break_even_pips"]["evidence"] == "MEASURED"
        assert row["break_even_pips"]["value"] == pytest.approx(bps / 10_000 * price / pip)
        assert row["break_even_pips"]["note"] == (
            f"per side on {symbol} at {price:.5g}, the median entry price"
        )
        # The declared 1 bp per side, in this pair's pips.
        assert row["reference_pips"] == {
            "value": pytest.approx(1.0 / 10_000 * price / pip),
            "evidence": "DECLARED",
            "note": row["break_even_pips"]["note"],
        }
    assert rows["EURUSD"]["reference_pips"]["value"] == pytest.approx(1.095)
    assert rows["USDJPY"]["reference_pips"]["value"] == pytest.approx(1.5)
    # No pip size for a metal in the repository: it stays in basis points.
    metal = rows["XAUUSD"]
    assert "pip_size" not in metal
    for key in ("break_even_pips", "reference_pips"):
        assert metal[key] == {"value": None, "evidence": "NOT_MEASURED", "note": PIPS_NO_METAL_SIZE}
    # Every symbol traded is a pair or a metal: no other symbol to name.
    assert "others" not in block


def test_the_money_per_lot_squares_with_the_report_by_hand(pairs: dict[str, Any]) -> None:
    costs = pairs["costs"]
    profits = sum(_profit(s, lots, a, b, k) for _, s, lots, a, b, k in PAIRS)
    commissions = sum(2 * round(COMMISSION_PER_LOT * t[2], 2) for t in PAIRS)
    lots = sum(t[2] for t in PAIRS)
    assert profits == pytest.approx(628.0) and commissions == pytest.approx(31.5)
    assert lots == pytest.approx(4.5)
    expected = (profits - commissions) / (2 * lots)  # 596.50 over 9.00 lots
    per_lot = costs["break_even_per_lot"]
    assert per_lot["evidence"] == "MEASURED"
    assert per_lot["value"] == pytest.approx(expected, rel=1e-9)
    assert per_lot["value"] == pytest.approx(66.2777778, rel=1e-6)
    assert costs["per_lot_currency"] == "USD"
    # Two currency pairs: their lots are added, and the note says so.
    assert per_lot["note"] == PER_LOT_NOTE_FEES_PAIRS.format(
        net="596.50", currency="USD", lots="9.00", count=2
    )


def test_with_a_metal_among_the_symbols_the_lots_are_not_added(mixed: dict[str, Any]) -> None:
    """A lot of XAUUSD (100 oz) is not a lot of EURUSD: no money per lot."""
    costs = mixed["costs"]
    assert costs["break_even_per_lot"] == {
        "value": None,
        "evidence": "NOT_MEASURED",
        "note": PER_LOT_MIXED,
    }
    assert "per_lot_currency" not in costs


def test_the_money_per_lot_uses_the_net_the_file_prints() -> None:
    """The per-lot net is each row's profit after the commission the file
    itemises, the stress tile's "with all": not the 0x row of the costs table,
    which re-prices each trade with the contract size the importer infers and
    is a few cents off on the sample."""
    inputs = build_inputs(
        None,
        DeclaredMetadata(),
        report_bytes=_sample_report(),
        report_filename="SyntheticSampleEA.html",
    )
    assert inputs.trades is not None and inputs.trade_lots
    costs, *_ = _costs(inputs)
    net = _stress(inputs, inputs.equity.frame)["trades"]["original"]["value"]
    printed = sum(t.pnl for t in inputs.trades.trades) + sum(inputs.reported_fees.values())
    assert net == pytest.approx(printed, abs=1e-6)
    lots = 2.0 * sum(inputs.trade_lots)
    per_lot = costs["break_even_per_lot"]
    assert per_lot["value"] == pytest.approx(net / lots, rel=1e-12)
    assert per_lot["note"] == PER_LOT_NOTE_FEES_PAIRS.format(
        net=f"{net:,.2f}", currency="USD", lots=f"{lots:,.2f}", count=2
    )
    zero = next(row for row in costs["rows"] if row["multiplier"] == 0)
    assert abs(zero["net_pnl"]["value"] - net) > 0.01


def test_one_pair_keeps_its_keys() -> None:
    result = _audit(synthetic_mt5_report(120), cost_bps_per_side=1.0)
    costs = result.model_dump(mode="json")["costs"]
    assert costs["pip_symbol"] == "EURUSD"
    assert "pips_by_symbol" not in costs
    bps = costs["break_even_bps"]["value"]
    inputs = build_inputs(
        None, DeclaredMetadata(), report_bytes=synthetic_mt5_report(120), report_filename="R.html"
    )
    assert inputs.trades is not None
    price = float(np.median([trade.entry_price for trade in inputs.trades.trades]))
    where = f"per side on EURUSD at {price:.5g}, the median entry price"
    assert costs["break_even_pips"] == {
        "value": pytest.approx(bps / 10_000 * price / 0.0001),
        "evidence": "MEASURED",
        "note": where,
    }
    assert costs["reference_pips"] == {
        "value": pytest.approx(1.0 / 10_000 * price / 0.0001),
        "evidence": "DECLARED",
        "note": where,
    }
    # One symbol: its lots are the money per lot's, with no note about pairs.
    per_lot = costs["break_even_per_lot"]
    assert per_lot["evidence"] == "MEASURED"
    assert per_lot["note"].startswith(PER_LOT_NOTE_FEES.split("{", 1)[0])
    assert "currency pairs" not in per_lot["note"]


@pytest.mark.parametrize(
    "fixture",
    ["tradingview_g1.csv", "ninjatrader.csv", "quantconnect_trades.csv", "myfxbook.csv"],
)
def test_a_file_outside_metatrader_gives_no_money_per_lot(fixture: str) -> None:
    """The reason is true of every such file: a Myfxbook export prints its
    'Units/Lots', but no contract size is assumed outside MetaTrader."""
    if fixture == "myfxbook.csv":
        data = synthetic_live_statement()
    else:
        data = (FIXTURES / fixture).read_bytes()
    inputs = build_inputs(None, DeclaredMetadata(), report_bytes=data, report_filename=fixture)
    if fixture == "myfxbook.csv":
        assert inputs.source_format == "myfxbook_csv"
    assert inputs.trade_lots is None
    costs, *_ = _costs(inputs)
    assert costs["break_even_per_lot"] == {
        "value": None,
        "evidence": "NOT_MEASURED",
        "note": PER_LOT_ONLY_METATRADER,
    }
    assert "per_lot_currency" not in costs


def test_an_exchange_prefix_is_dropped() -> None:
    assert _symbol_code("OANDA:XAUUSD") == "XAUUSD"
    assert _symbol_code("XAUUSD.r") == "XAUUSD"
    assert fx_pair(["FX:EURUSD", "EURUSD.m"], {}) == "EURUSD"
    assert fx_pair(["OANDA:XAUUSD"], {}) is None
    # A platform's description with a colon in it is not a prefix.
    assert fx_pair([], {"symbol": "EURUSD (Euro: US Dollar)"}) == "EURUSD"
    one = tuple(row for row in PREFIXED if row[0] == "FX:EURUSD")
    costs = _audit(_mt5_report(one)).model_dump(mode="json")["costs"]
    assert costs["pip_symbol"] == "EURUSD" and "pips_by_symbol" not in costs


@pytest.fixture(scope="module")
def prefixed() -> AuditResult:
    return _audit(_mt5_report(PREFIXED), cost_bps_per_side=1.0)


def test_other_symbols_are_named_and_a_prefixed_metal_keeps_its_name(
    prefixed: AuditResult,
) -> None:
    costs = prefixed.model_dump(mode="json")["costs"]
    block = costs["pips_by_symbol"]
    assert [row["symbol"] for row in block["rows"]] == ["EURUSD", "XAUUSD"]
    assert [row["trades"] for row in block["rows"]] == [3, 1]
    assert block["rows"][1]["break_even_pips"]["note"] == PIPS_NO_METAL_SIZE
    # USDMXN and US30 have no pip size: they are named, most traded first.
    assert block["others"] == {
        "symbols": ["USDMXN", "US30"],
        "note": PIPS_OTHERS_NOTE.format(symbols="USDMXN, US30"),
    }
    assert costs["break_even_per_lot"]["note"] == PER_LOT_MIXED


@pytest.mark.parametrize("locale", LOCALES)
def test_the_report_names_the_symbols_left_in_bps(prefixed: AuditResult, locale: str) -> None:
    page = render_html(prefixed, watermark=False, locale=locale)
    text = _visible(page)
    note = prefixed.model_dump(mode="json")["costs"]["pips_by_symbol"]["others"]["note"]
    assert localize(note, locale) in text
    assert "USDMXN, US30" in localize(note, locale)
    assert "OANDAX" not in text and "FXEURU" not in text
    assert find_claims(page) == []
    if locale != "en":
        assert untranslated(prefixed.model_dump(mode="json"), locale) == []
        assert "the audit defines no pip size" not in text


@pytest.mark.parametrize(("trades", "lots_added"), [(GOLD, True), (METALS, False)])
def test_metals_alone_have_no_table_in_pips(
    trades: tuple[tuple[str, str, float, float, float, float], ...], lots_added: bool
) -> None:
    """Gold alone (or gold and silver) has no figure in pips: no table whose
    only rows read "not measured"."""
    result = _audit(_mt5_report(trades), cost_bps_per_side=1.0)
    costs = result.model_dump(mode="json")["costs"]
    assert "pips_by_symbol" not in costs and "break_even_pips" not in costs
    per_lot = costs["break_even_per_lot"]
    if lots_added:
        # One symbol (XAUUSD.r is XAUUSD): its own lots, no pairs to add.
        assert per_lot["evidence"] == "MEASURED"
        assert per_lot["note"].startswith(PER_LOT_NOTE_FEES.split("{", 1)[0])
        assert "currency pairs" not in per_lot["note"]
    else:
        assert per_lot["note"] == PER_LOT_MIXED
    for locale in LOCALES:
        page = render_html(result, watermark=False, locale=locale)
        assert LABELS[locale]["cost_pips_title"] not in _visible(page)


def _visible(page: str) -> str:
    page = re.sub(r"<(style|svg|script)\b.*?</\1>", " ", page, flags=re.S)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())


@pytest.mark.parametrize("locale", LOCALES)
def test_the_report_says_the_pips_and_the_money_per_lot(locale: str) -> None:
    result = _audit(_mt5_report(PAIRS), cost_bps_per_side=1.0, locale=locale)
    data = result.model_dump(mode="json")
    costs = data["costs"]
    labels = LABELS[locale]
    page = render_html(result, watermark=False, locale=locale)
    text = _visible(page)
    rows = {row["symbol"]: row for row in costs["pips_by_symbol"]["rows"]}
    eur = f"{rows['EURUSD']['break_even_pips']['value']:,.1f}"
    jpy = f"{rows['USDJPY']['break_even_pips']['value']:,.1f}"
    lot = f"{costs['break_even_per_lot']['value']:,.2f}"
    tile = (
        f"{labels['kpi_breakeven']} ({labels['bps_side']}; ≈ "
        + labels["kpi_pips_on"].format(pips=eur, symbol="EURUSD")
        + " / "
        + labels["kpi_pips_on"].format(pips=jpy, symbol="USDJPY")
        + "; "
        + labels["kpi_per_lot"].format(value=lot, currency="USD")
        + ")"
    )
    assert tile in text
    # The tile's figure is still the basis points, unchanged.
    assert f"{costs['break_even_bps']['value']:,.2f} {tile}" in text
    assert labels["cost_pips_title"] in text
    assert localize(PIPS_BY_SYMBOL_NOTE, locale) in text
    assert f"{KEY_LABELS[locale]['break_even_per_lot']} {lot} USD" in text
    assert localize(costs["break_even_per_lot"]["note"], locale) in text
    assert find_claims(text) == []
    assert find_claims(page) == []
    if locale != "en":
        assert untranslated(data, locale) == []
        for english in ("per side on", "the whole history", "per lot and side", "currency pairs"):
            assert english not in text


@pytest.mark.parametrize("locale", LOCALES)
def test_with_a_metal_the_report_says_why_there_is_no_money_per_lot(locale: str) -> None:
    result = _audit(_mt5_report(TRADES), cost_bps_per_side=1.0, locale=locale)
    data = result.model_dump(mode="json")
    costs = data["costs"]
    labels = LABELS[locale]
    text = _visible(render_html(result, watermark=False, locale=locale))
    rows = {row["symbol"]: row for row in costs["pips_by_symbol"]["rows"]}
    eur = f"{rows['EURUSD']['break_even_pips']['value']:,.1f}"
    jpy = f"{rows['USDJPY']['break_even_pips']['value']:,.1f}"
    # The tile keeps the pips and says no money per lot.
    tile = (
        f"{labels['kpi_breakeven']} ({labels['bps_side']}; ≈ "
        + labels["kpi_pips_on"].format(pips=eur, symbol="EURUSD")
        + " / "
        + labels["kpi_pips_on"].format(pips=jpy, symbol="USDJPY")
        + ")"
    )
    assert tile in text
    assert localize(PER_LOT_MIXED, locale) in text
    assert localize(PIPS_NO_METAL_SIZE, locale) in text
    assert find_claims(text) == []
    if locale != "en":
        assert untranslated(data, locale) == []
        for english in ("not added together", "no pip size"):
            assert english not in text


@pytest.mark.parametrize("locale", LOCALES)
def test_the_tile_keeps_the_provenance_of_every_figure_it_shows(
    pairs: dict[str, Any], locale: str
) -> None:
    labels = LABELS[locale]
    label = next(
        name for name, _, _ in _kpi_list(pairs, labels) if name.startswith(labels["kpi_breakeven"])
    )
    assert _kpi_evidence(label, labels, pairs) == "MEASURED"
    changed = {**pairs, "costs": {**pairs["costs"]}}
    changed["costs"]["break_even_per_lot"] = {
        **pairs["costs"]["break_even_per_lot"],
        "evidence": "DECLARED",
    }
    assert _kpi_evidence(label, labels, changed) == "DECLARED"


@pytest.mark.parametrize("locale", LOCALES)
def test_the_plan_quotes_the_history_own_figures(
    mixed: dict[str, Any], pairs: dict[str, Any], locale: str
) -> None:
    finding, actions = _costs_step(mixed, "WEAK", locale)
    rows = {row["symbol"]: row for row in mixed["costs"]["pips_by_symbol"]["rows"]}
    assert f"EURUSD {rows['EURUSD']['break_even_pips']['value']:,.2f}" in finding
    assert f"USDJPY {rows['USDJPY']['break_even_pips']['value']:,.2f}" in finding
    # The metal has no pips, and with it the lots are not added: no money per lot.
    assert "XAUUSD" not in finding and " USD " not in finding
    # The generic EURUSD-at-1.10 line is gone: the history has its own figures.
    assert not any("1.10" in action for action in actions)
    # The broker line names every symbol traded, the metal too.
    assert f"EURUSD, USDJPY {AND[locale]} XAUUSD." in actions[0]
    assert find_claims(" ".join([finding, *actions])) == []
    finding, actions = _costs_step(pairs, "WEAK", locale)
    assert f"{pairs['costs']['break_even_per_lot']['value']:,.2f} USD" in finding
    assert f"EURUSD {AND[locale]} USDJPY." in actions[0]
    assert find_claims(" ".join([finding, *actions])) == []


def _plan_data(bps: float, symbols: list[str], others: list[str] | None = None) -> dict[str, Any]:
    """A costs section with one pips row per symbol (a metal reads not measured)."""

    def pips(value: float | None) -> dict[str, Any]:
        if value is None:
            return {"value": None, "evidence": "NOT_MEASURED", "note": PIPS_NO_METAL_SIZE}
        return {"value": value, "evidence": "MEASURED", "note": ""}

    rows = [
        {
            "symbol": name,
            "trades": 10 - index,
            "break_even_pips": pips(None if name.startswith("XA") else bps * 1.1),
            "reference_pips": pips(None if name.startswith("XA") else 0.55),
        }
        for index, name in enumerate(symbols)
    ]
    block: dict[str, Any] = {"note": PIPS_BY_SYMBOL_NOTE, "rows": rows}
    if others:
        block["others"] = {"symbols": others, "note": PIPS_OTHERS_NOTE.format(symbols="…")}
    return {
        "costs": {
            "status": "MEASURED",
            "break_even_bps": {"value": bps, "evidence": "MEASURED", "note": ""},
            "reference_bps": {"value": 0.5, "evidence": "NOT_MEASURED", "note": ""},
            "pips_by_symbol": block,
            "break_even_per_lot": {"value": None, "evidence": "NOT_MEASURED", "note": ""},
        }
    }


EACH_SYMBOL = {"es": "cada símbolo que operas", "en": "each symbol you trade"}
EACH_SYMBOL["pt"] = "cada símbolo que você opera"


@pytest.mark.parametrize("locale", LOCALES)
def test_the_plan_names_the_metal_traded_most(locale: str) -> None:
    _, actions = _costs_step(_plan_data(3.0, ["XAUUSD", "EURUSD"]), "WEAK", locale)
    assert f"XAUUSD {AND[locale]} EURUSD." in actions[0]
    # A partial list would leave a symbol out: the line says each symbol instead.
    for data in (
        _plan_data(3.0, ["EURUSD"], others=["US30"]),
        _plan_data(3.0, ["EURUSD", "GBPUSD", "AUDUSD", "XAUUSD"]),
    ):
        _, actions = _costs_step(data, "WEAK", locale)
        assert EACH_SYMBOL[locale] in actions[0] and "1.10" not in actions[0]
        assert find_claims(actions[0]) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_the_plan_keeps_the_example_when_the_ledger_already_loses(locale: str) -> None:
    """MT4 statement: two XAUUSD trades and one EURUSD, negative before any
    extra cost. The finding quotes no pips of its own, so the example stays."""
    data = (FIXTURES / "mt4_statement.htm").read_bytes()
    result = _audit(data, cost_bps_per_side=1.5).model_dump(mode="json")
    assert result["costs"]["break_even_bps"]["value"] < 0
    finding, actions = _costs_step(result, "WEAK", locale)
    assert "EURUSD" not in finding
    assert "1.10" in actions[0]
    _, actions = _costs_step(_plan_data(-2.0, ["XAUUSD", "EURUSD"]), "WEAK", locale)
    assert "1.10" in actions[0]


@pytest.mark.parametrize("locale", LOCALES)
def test_the_plan_keeps_the_generic_line_without_figures(locale: str) -> None:
    data = {
        "costs": {
            "status": "MEASURED",
            "break_even_bps": {"value": 4.0, "evidence": "MEASURED", "note": ""},
            "reference_bps": {"value": 10.0, "evidence": "NOT_MEASURED", "note": ""},
            "break_even_per_lot": {"value": None, "evidence": "NOT_MEASURED", "note": ""},
        }
    }
    _, actions = _costs_step(data, "WEAK", locale)
    assert "1.10" in actions[0]


def _ladder_row(evidence: str, bps: float) -> dict[str, Any]:
    return {
        "key": "reference_cost",
        "days": 250,
        "cost_bps_per_side": {"value": bps, "evidence": evidence, "note": ""},
        "pass": {"value": 0.25, "evidence": "MEASURED", "note": ""},
        "main_risk": "none",
    }


@pytest.mark.parametrize("locale", LOCALES)
def test_the_ladder_row_names_the_cost_it_uses(locale: str) -> None:
    labels = LABELS[locale]
    declared = _challenge_ladder_label(_ladder_row("DECLARED", 2.0), labels)
    assumed = _challenge_ladder_label(_ladder_row("NOT_MEASURED", 0.5), labels)
    assert declared == labels["ch_ladder_cost_declared"].format(bps="2")
    # Without a declared cost the row reads as it always did.
    assert assumed == labels["ch_ladder_cost"].format(bps="0.5")
    assert declared != assumed
    scenarios = {
        "status": "MEASURED",
        "program": {"firm": "FTMO", "program": "2-Step", "phases": 1},
        "rows": [_ladder_row("DECLARED", 2.0)],
    }
    shown = _challenge_ladder_html(scenarios, locale, labels)
    assert html.escape(declared) in shown and 'class="badge DECLARED"' in shown
    assert find_claims(declared) == [] and find_claims(assumed) == []


def test_the_ladder_uses_the_declared_cost_and_keeps_the_rest() -> None:
    """The simulator's cost rung charges the cost the client declared; the
    other rungs and the row without a declaration do not change."""
    key = "ftmo-2step-phase1"

    def rows(**declared: Any) -> dict[str, dict[str, Any]]:
        inputs = build_inputs(
            None,
            DeclaredMetadata(challenge=key, oos_start="2024-06-03", trials=120, **declared),
            report_bytes=_sample_report(),
            report_filename="SyntheticSampleEA.html",
        )
        result = run_audit(inputs, bootstrap_samples=30, risk_samples=30, challenge_samples=200)
        assert result.challenge is not None
        return {row["key"]: row for row in result.challenge["scenarios"]["rows"]}

    declared, blank = rows(cost_bps_per_side=2.0), rows()
    assert declared["reference_cost"]["cost_bps_per_side"]["value"] == 2.0
    assert declared["reference_cost"]["cost_bps_per_side"]["evidence"] == "DECLARED"
    assert blank["reference_cost"]["cost_bps_per_side"]["evidence"] == "NOT_MEASURED"
    assert blank["reference_cost"]["cost_bps_per_side"]["value"] == 0.5
    # A larger cost per side never helps the rung.
    assert declared["reference_cost"]["pass"]["value"] <= blank["reference_cost"]["pass"]["value"]
    for name in ("full", "in_sample", "out_of_sample"):
        assert declared[name] == blank[name]
    for locale in LOCALES:
        labels = LABELS[locale]
        assert _challenge_ladder_label(declared["reference_cost"], labels) == labels[
            "ch_ladder_cost_declared"
        ].format(bps="2")
        assert _challenge_ladder_label(blank["reference_cost"], labels) == labels[
            "ch_ladder_cost"
        ].format(bps="0.5")


def test_every_new_label_exists_in_every_language_and_passes_the_guard() -> None:
    keys = (
        "kpi_pips_on",
        "kpi_per_lot",
        "kpi_per_lot_units",
        "cost_pips_title",
        "cost_symbol",
        "cost_median_entry",
        "ch_ladder_cost_declared",
    )
    for locale in LOCALES:
        for key in keys:
            assert LABELS[locale][key]
            assert find_claims(LABELS[locale][key]) == []
        assert find_claims(KEY_LABELS[locale]["break_even_per_lot"]) == []
    assert LABELS["pt"]["kpi_per_lot"] != LABELS["en"]["kpi_per_lot"]
    assert KEY_LABELS["pt"]["break_even_per_lot"] != KEY_LABELS["en"]["break_even_per_lot"]


def test_every_new_reason_reads_in_every_language_and_passes_the_guard() -> None:
    values = {"net": "1,234.50", "currency": "USD", "lots": "9.00", "count": "2"}
    for english in (
        PER_LOT_NOTE.format(**values),
        PER_LOT_NOTE_FEES.format(**values),
        PER_LOT_NOTE_PAIRS.format(**values),
        PER_LOT_NOTE_FEES_PAIRS.format(**values),
        PER_LOT_NOTE.format(**{**values, "currency": "in file units"}),
        PER_LOT_ONLY_METATRADER,
        PER_LOT_MIXED,
        PIPS_OTHERS_NOTE.format(symbols="USDMXN, US30"),
    ):
        shown = {locale: localize(english, locale) for locale in LOCALES}
        assert shown["en"] == english
        assert len(set(shown.values())) == 3, english
        for text in shown.values():
            assert find_claims(text) == []
            assert "{" not in text
    assert "en unidades del archivo" in localize(
        PER_LOT_NOTE.format(**{**values, "currency": "in file units"}), "es"
    )
