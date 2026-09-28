"""Adversarial money and dependence cases that a buyer would actually see."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from audit_fixtures import tampered_mt5_tester_bytes

from quant_trade.audit.engine import _reconciliation, dependence_adjusted_psr, run_audit
from quant_trade.audit.schema import DeclaredMetadata, ParseError, build_inputs, parse_trades_csv

NOW = datetime(2026, 9, 27, tzinfo=UTC)
MT5 = Path(__file__).parent / "fixtures" / "audit_imports" / "mt5_tester.html"
MT5_HISTORY = MT5.with_name("mt5_history.html")


def _run(inputs):  # type: ignore[no-untyped-def]
    return run_audit(
        inputs,
        now=NOW,
        audit_id="integrity-case",
        bootstrap_samples=50,
        risk_samples=50,
        challenge_samples=50,
    )


def _trades_csv(**extra: object) -> bytes:
    row = {
        "entry_time": "2024-01-02T09:00:00Z",
        "exit_time": "2024-01-02T10:00:00Z",
        "quantity": 100,
        "entry_price": 100,
        "exit_price": 100.01,
        "currency": "USD",
        **extra,
    }
    return pd.DataFrame([row]).to_csv(index=False).encode()


def test_explicit_commission_turns_one_gross_profit_into_net_loss() -> None:
    parsed = parse_trades_csv(_trades_csv(commission=10))
    assert parsed.trades[0].pnl == pytest.approx(1.0)
    assert parsed.fees == [10.0]
    assert parsed.currency == "USD"
    from quant_trade.audit.costs import recost_trades

    zero = recost_trades(parsed.trades, parsed.sides, 0.0, reported_costs=parsed.fees)[0]
    assert zero.gross_pnl == pytest.approx(1.0)
    assert zero.net_pnl == pytest.approx(-9.0)


def test_declared_net_and_signed_swap_do_not_double_count() -> None:
    parsed = parse_trades_csv(_trades_csv(commission=-10, swap=2, net_pnl=-7))
    assert parsed.fees == [8.0]
    assert parsed.client_pnl_basis == "net"
    assert parsed.client_pnl == [-7]
    from quant_trade.audit import redflags
    from quant_trade.audit.schema import parse_equity_csv

    dates = pd.bdate_range("2024-01-01", periods=40, tz="UTC")
    curve = pd.DataFrame({"timestamp": dates, "equity": 10000 + np.arange(40)})
    series = parse_equity_csv(curve.to_csv(index=False).encode())
    flags = redflags.scan(
        series,
        periods_per_year=252,
        declared=DeclaredMetadata(cost_bps_per_side=5),
        trades=parsed,
        recomputed_pnl=[1.0],
    )
    assert "TRADE_PNL_MISMATCH" not in {flag.code for flag in flags}
    ambiguous = parse_trades_csv(_trades_csv(commission=10, pnl=-9))
    assert ambiguous.client_pnl_basis == "ambiguous"
    assert any("ambiguous" in item for item in ambiguous.warnings)
    unknown = parse_trades_csv(_trades_csv(commission=10, exchange_rebate=1))
    assert any("exchange_rebate" in item for item in unknown.warnings)


def test_mixed_currency_and_unreadable_cost_are_refused() -> None:
    data = pd.read_csv(__import__("io").BytesIO(_trades_csv(commission=10)))
    mixed = pd.concat([data, data.assign(currency="EUR")], ignore_index=True)
    with pytest.raises(ParseError, match="mixes currencies"):
        parse_trades_csv(mixed.to_csv(index=False).encode())
    with pytest.raises(ParseError, match="unreadable commission"):
        parse_trades_csv(_trades_csv(commission="n/a"))


def test_mt5_printed_balance_conflict_does_not_inflate_measured_return() -> None:
    changed = tampered_mt5_tester_bytes(MT5.read_bytes())
    assert changed.count(b"11 063.05") == 1
    inputs = build_inputs(
        None,
        DeclaredMetadata(cost_bps_per_side=1),
        report_bytes=changed,
        report_filename="mt5_tester.html",
        now=NOW,
    )
    result = _run(inputs)
    assert result.performance["total_return"]["value"] == pytest.approx(0.006305)
    assert result.reconciliation is not None
    assert result.reconciliation["status"] == "CONTRADICTION"
    assert result.reconciliation["difference"]["value"] == pytest.approx(1000.0)
    assert result.forensics is not None
    assert any(
        item["id"] == "BALANCE_CHAIN" and item["status"] == "SIGNAL"
        for item in result.forensics["checks"]
    )
    assert next(d for d in result.verdict.dimensions if d.name == "data_quality").status == "FAIL"

    consistent = changed.replace(b"11 063.05", b"10 063.05")
    control = _run(
        build_inputs(
            None,
            DeclaredMetadata(cost_bps_per_side=1),
            report_bytes=consistent,
            report_filename="mt5_tester.html",
            now=NOW,
        )
    )
    assert control.reconciliation is not None
    assert control.reconciliation["status"] == "MATCH"


@pytest.mark.parametrize("filename", ["mt4_statement.htm", "mt5_history.html"])
def test_withdrawal_after_last_trade_does_not_create_false_contradiction(filename: str) -> None:
    path = MT5.with_name(filename)
    inputs = build_inputs(
        None,
        DeclaredMetadata(cost_bps_per_side=1),
        report_bytes=path.read_bytes(),
        report_filename=filename,
        now=NOW,
    )
    result = _run(inputs)
    assert result.reconciliation is not None
    assert result.reconciliation["status"] == "MATCH"
    assert result.reconciliation["difference"]["value"] == pytest.approx(0.0)
    assert "MONETARY_RECONCILIATION_MISMATCH" not in {flag["code"] for flag in result.red_flags}


def test_legitimate_deposit_rounding_and_unknown_curve_currency() -> None:
    dates = pd.date_range("2024-01-01", periods=3, tz="UTC")
    curve = pd.DataFrame({"timestamp": dates, "equity": [10000.0, 10010.0, 11015.5]})
    trades = pd.DataFrame(
        [
            {
                "entry_time": "2024-01-01T09:00:00Z",
                "exit_time": "2024-01-02T10:00:00Z",
                "quantity": 1,
                "entry_price": 100,
                "exit_price": 110,
                "currency": "USD",
            },
            {
                "entry_time": "2024-01-02T11:00:00Z",
                "exit_time": "2024-01-03T10:00:00Z",
                "quantity": 1,
                "entry_price": 100,
                "exit_price": 105,
                "currency": "USD",
            },
        ]
    )
    inputs = build_inputs(
        curve.to_csv(index=False).encode(),
        DeclaredMetadata(),
        trades_bytes=trades.to_csv(index=False).encode(),
        now=NOW,
    )
    # A deposit inside the observed period explains the curve's larger value.
    inputs = replace(inputs, cash_flows=[(datetime(2024, 1, 3, 8, tzinfo=UTC), 1000.0)])
    matched, flags = _reconciliation(inputs)
    assert matched["status"] == "MATCH"
    assert matched["difference"]["value"] == pytest.approx(0.5)
    assert matched["coverage"]["trade_currency"] == "USD"
    assert matched["coverage"]["curve_currency"] == "not supplied"
    assert matched["currency"] == "UNKNOWN"
    assert flags == []

    # An unexplained change in a separate curve remains inconclusive: it is
    # NOT_MEASURED with its reason and raises no red flag.
    without_flow, flags = _reconciliation(replace(inputs, cash_flows=[]))
    assert without_flow["status"] == "NOT_MEASURED"
    assert "could explain the difference" in without_flow["reason"]
    assert flags == []


def test_build_commit_sha_is_declared_only_when_explicit_and_valid() -> None:
    dates = pd.bdate_range("2024-01-01", periods=40, tz="UTC")
    curve = pd.DataFrame({"timestamp": dates, "equity": 10000 + np.arange(40)})
    inputs = build_inputs(curve.to_csv(index=False).encode(), DeclaredMetadata(), now=NOW)
    valid = run_audit(inputs, now=NOW, source_commit_sha="A" * 40)
    absent = run_audit(inputs, now=NOW, source_commit_sha="not-a-sha")
    assert valid.engine["source_commit_sha"] == {
        "value": "a" * 40,
        "evidence": "DECLARED",
        "note": "",
    }
    assert absent.engine["source_commit_sha"]["evidence"] == "NOT_MEASURED"


def _seed_812_files() -> tuple[bytes, bytes, bytes]:
    rng = np.random.default_rng(812)
    pnl = rng.normal(2.0, 20.0, 519)
    pnl *= 1040.13 / pnl.sum()
    dates = pd.bdate_range("2024-01-02", periods=519, tz="UTC")
    rows = pd.DataFrame(
        {
            "entry_time": dates - pd.Timedelta(hours=1),
            "exit_time": dates,
            "quantity": 1,
            "entry_price": 100.0,
            "exit_price": 100.0 + pnl,
            "side": "long",
            "currency": "USD",
        }
    )
    curve_dates = pd.DatetimeIndex([dates[0] - pd.Timedelta(days=1), *dates])
    values = np.r_[10000.0, 10000.0 + np.cumsum(pnl)]

    def curve(multiplier: float) -> bytes:
        frame = pd.DataFrame(
            {"timestamp": curve_dates, "equity": 10000 + (values - 10000) * multiplier}
        )
        return frame.to_csv(index=False).encode()

    return rows.to_csv(index=False).encode(), curve(1.0), curve(20.0)


def test_seed_812_scaled_curve_is_not_measured_without_a_flag() -> None:
    """A separate curve 20x the trades' variation (a scaled index, floating
    P&L or undisclosed flows look the same) cannot be reconciled: the section
    says NOT_MEASURED and why, and no red flag or data-quality penalty follows,
    because genuine files with separate curves produce the same gap."""
    trades, honest_curve, inflated_curve = _seed_812_files()
    declared = DeclaredMetadata(cost_bps_per_side=5)
    control = _run(build_inputs(honest_curve, declared, trades_bytes=trades, now=NOW))
    suspect = _run(build_inputs(inflated_curve, declared, trades_bytes=trades, now=NOW))
    assert control.performance["total_return"]["value"] == pytest.approx(0.104013, abs=1e-6)
    assert suspect.performance["total_return"]["value"] == pytest.approx(2.08026, abs=1e-5)
    assert control.reconciliation is not None and control.reconciliation["status"] == "MATCH"
    assert next(d for d in control.verdict.dimensions if d.name == "data_quality").status == "PASS"
    assert suspect.reconciliation is not None
    assert suspect.reconciliation["status"] == "NOT_MEASURED"
    assert suspect.reconciliation["difference"]["value"] > 19000
    assert "could explain the difference" in suspect.reconciliation["reason"]
    assert not any(f["code"].startswith("MONETARY_") for f in suspect.red_flags)
    quality = {d.name: d.status for d in suspect.verdict.dimensions}["data_quality"]
    assert quality == {d.name: d.status for d in control.verdict.dimensions}["data_quality"]


def test_dependent_2000_returns_cannot_receive_class_a_from_plain_psr() -> None:
    rng = np.random.default_rng(71)
    shocks = rng.normal(0, 0.01, 2000)
    dependent = np.empty(2000)
    dependent[0] = shocks[0]
    for at in range(1, len(dependent)):
        dependent[at] = 0.9 * dependent[at - 1] + shocks[at]
    # Choose a positive observed mean near the dependence-adjusted decision bar.
    dependent += 0.004875
    dates = pd.bdate_range("2016-01-01", periods=len(dependent), tz="UTC")
    curve = pd.DataFrame({"timestamp": dates, "equity": 10000 * np.cumprod(1 + dependent)})
    result = _run(
        build_inputs(
            curve.to_csv(index=False).encode(), DeclaredMetadata(cost_bps_per_side=5), now=NOW
        )
    )
    adjusted = dependence_adjusted_psr(pd.Series(dependent))["psr"]["value"]
    assert 0.0 < adjusted < 0.95
    assert result.significance["psr"]["value"] >= adjusted
    engine_adjusted = result.significance["dependence"]["psr"]
    assert engine_adjusted["evidence"] == "MEASURED"
    statistical = next(d for d in result.verdict.dimensions if d.name == "statistical_significance")
    # The verdict grades the dependence-adjusted PSR, not the plain one.
    assert statistical.inputs["psr"]["value"] == pytest.approx(engine_adjusted["value"])
    assert statistical.inputs["psr"]["value"] < statistical.inputs["psr_unadjusted"]["value"]
    assert result.verdict.overall != "A"


def test_independent_and_short_samples_keep_conservative_evidence() -> None:
    rng = np.random.default_rng(101)
    independent = pd.Series(rng.normal(0.001, 0.01, 2000))
    adjustment = dependence_adjusted_psr(independent)
    assert adjustment["ratio"]["value"] >= 1.0
    assert 0 < adjustment["psr"]["value"] <= 1.0

    short = pd.Series(rng.normal(0.001, 0.01, 20))
    assert dependence_adjusted_psr(short)["psr"]["evidence"] == "NOT_MEASURED"
    dates = pd.bdate_range("2024-01-01", periods=21, tz="UTC")
    curve = pd.DataFrame(
        {
            "timestamp": dates,
            "equity": 10000 * np.cumprod(1 + np.r_[0.0, short.to_numpy()]),
        }
    )
    result = _run(
        build_inputs(
            curve.to_csv(index=False).encode(), DeclaredMetadata(cost_bps_per_side=5), now=NOW
        )
    )
    assert result.verdict.overall != "A"
    assert "TOO_FEW_OBSERVATIONS" in {flag["code"] for flag in result.red_flags}


def test_variants_bad_dates_cannot_feed_cscv() -> None:
    dates = pd.bdate_range("2024-01-01", periods=40, tz="UTC")
    equity = pd.DataFrame({"timestamp": dates, "equity": 10000 + np.arange(40)})
    variants = pd.DataFrame({"timestamp": dates, "a": 0.01, "b": 0.02})
    variants.loc[10, "timestamp"] = variants.loc[9, "timestamp"]
    with pytest.raises(ParseError, match="unique"):
        build_inputs(
            equity.to_csv(index=False).encode(),
            DeclaredMetadata(),
            variants_bytes=variants.to_csv(index=False).encode(),
            now=NOW,
        )
    variants.loc[10, "timestamp"] = dates[10] + pd.Timedelta(hours=1)
    with pytest.raises(ParseError, match="align"):
        build_inputs(
            equity.to_csv(index=False).encode(),
            DeclaredMetadata(),
            variants_bytes=variants.to_csv(index=False).encode(),
            now=NOW,
        )


def _mt5_with_open_position() -> bytes:
    clean = MT5.read_bytes()
    last_deal = b"<td>10 063.05</td><td>end of test</td></tr>"
    opened = (
        b'\n   <tr bgcolor="#FFFFFF" align=right><td>2024.01.08 11:00:00</td><td>11</td>'
        b"<td>EURUSD</td><td>buy</td><td>in</td><td>0.1</td><td>1.09000</td><td>11</td>"
        b"<td>-5.00</td><td>0.00</td><td>0.00</td><td>10 058.05</td><td></td></tr>"
    )
    assert clean.count(last_deal) == 1
    return clean.replace(last_deal, last_deal + opened)


def test_mt5_position_open_at_the_end_is_not_a_monetary_contradiction() -> None:
    """An entry deal still open at the end moves the balance by its commission
    without appearing in the closed trades: the gap (5.00, above the 1 bp
    tolerance) cannot be reconciled, so it is NOT_MEASURED, never a
    contradiction that forces class D."""
    inputs = build_inputs(
        None,
        DeclaredMetadata(cost_bps_per_side=1),
        report_bytes=_mt5_with_open_position(),
        report_filename="mt5_tester.html",
        now=NOW,
    )
    assert any("still open at the end of the report" in w for w in inputs.warnings)
    result = _run(inputs)
    assert result.reconciliation is not None
    assert result.reconciliation["status"] == "NOT_MEASURED"
    assert result.reconciliation["difference"]["value"] == pytest.approx(-5.0)
    assert "open positions" in result.reconciliation["reason"]
    codes = {(flag["code"], flag["severity"]) for flag in result.red_flags}
    assert ("MONETARY_RECONCILIATION_MISMATCH", "FAIL") not in codes


def test_open_position_does_not_hide_a_tampered_balance_cell() -> None:
    report = _mt5_with_open_position()
    original = b"<td>10 058.05</td><td></td></tr>"
    assert report.count(original) == 1
    tampered = report.replace(original, b"<td>11 058.05</td><td></td></tr>")
    inputs = build_inputs(
        None,
        DeclaredMetadata(cost_bps_per_side=1),
        report_bytes=tampered,
        report_filename="mt5_tester.html",
        now=NOW,
    )
    result = _run(inputs)
    assert result.reconciliation is not None
    assert result.reconciliation["status"] == "CONTRADICTION"
    assert result.reconciliation["difference"]["value"] == pytest.approx(995.0)
    assert ("MONETARY_RECONCILIATION_MISMATCH", "FAIL") in {
        (flag["code"], flag["severity"]) for flag in result.red_flags
    }


@pytest.mark.parametrize(
    ("code", "detail"),
    [
        (
            "MONETARY_RECONCILIATION_MISMATCH",
            "printed final balance differs from initial balance plus flows and net closed P&L "
            "by 9,082,362.36 in file units; the return was rebuilt from deal amounts",
        ),
        (
            "MONETARY_RECONCILIATION_UNEXPLAINED",
            "separate curve and closed trades differ by -9,082,362.36 in file units; provide "
            "cash flows, currency conversion and open-position valuation to reconcile them",
        ),
    ],
)
def test_monetary_details_localize_unit_phrase_and_number_grouping(code: str, detail: str) -> None:
    from quant_trade.audit.i18n import localize
    from quant_trade.audit.report import render_html

    changed = tampered_mt5_tester_bytes(MT5.read_bytes())
    inputs = build_inputs(
        None,
        DeclaredMetadata(cost_bps_per_side=1),
        report_bytes=changed,
        report_filename="mt5_tester.html",
        now=NOW,
    )
    result = _run(inputs)
    flag = {"code": code, "severity": "FAIL", "detail": detail, "value": 9082362.36}
    result = result.model_copy(update={"red_flags": [flag]})
    expected = {
        "es": ("9.082.362,36 en unidades del archivo", "en 330,61 en unidades del archivo"),
        "pt": ("9.082.362,36 em unidades do arquivo", "em 330,61 em unidades do arquivo"),
    }
    for locale, (grouped, small) in expected.items():
        page = render_html(result, watermark=False, free_mode=True, locale=locale)
        assert "in file units" not in page
        assert "9,082,362.36" not in page
        assert grouped in page
        short = localize(
            detail.replace("-9,082,362.36", "330.61").replace("9,082,362.36", "330.61"), locale
        )
        assert small in short and "in file units" not in short
    english = render_html(result, watermark=False, free_mode=True, locale="en")
    assert "9,082,362.36 in file units" in english


def _mt5_history_with_partial_close() -> bytes:
    """The EURUSD entry remains half open after its 0.10-lot close.

    The Positions row includes only the closed half's 0.18 entry commission,
    rounded to cents, plus its 0.35 exit commission. The full 0.35 entry
    commission is already charged in the Deals balance chain.
    """
    report = MT5_HISTORY.read_bytes()
    opening = b"<td nowrap>in</td><td nowrap>0.10</td><td nowrap>1.08500</td>"
    assert report.count(opening) == 1
    report = report.replace(
        opening, b"<td nowrap>in</td><td nowrap>0.20</td><td nowrap>1.08500</td>"
    )
    position_cost = b'<td class="">-0.70</td><td class="">-0.62</td>'
    assert report.count(position_cost) == 1
    return report.replace(position_cost, b'<td class="">-0.53</td><td class="">-0.62</td>')


def test_mt5_history_partial_close_keeps_clean_balance_inconclusive() -> None:
    inputs = build_inputs(
        None,
        DeclaredMetadata(cost_bps_per_side=1),
        report_bytes=_mt5_history_with_partial_close(),
        report_filename="mt5_history.html",
        now=NOW,
    )
    assert any("opened in the report were not closed" in w for w in inputs.warnings)
    result = _run(inputs)
    assert result.reconciliation is not None
    assert result.reconciliation["status"] == "NOT_MEASURED"
    assert result.reconciliation["difference"]["value"] == pytest.approx(-0.17)
    assert result.forensics is not None
    assert any(
        check["id"] == "BALANCE_CHAIN" and check["status"] == "CLEAN"
        for check in result.forensics["checks"]
    )
    assert ("MONETARY_RECONCILIATION_MISMATCH", "FAIL") not in {
        (flag["code"], flag["severity"]) for flag in result.red_flags
    }


def test_mt5_history_partial_close_still_exposes_tampered_balance() -> None:
    report = _mt5_history_with_partial_close()
    original = b"<td nowrap>1 009.40</td><td nowrap>[tp 1.08700]</td>"
    assert report.count(original) == 1
    report = report.replace(original, b"<td nowrap>1 019.40</td><td nowrap>[tp 1.08700]</td>")
    inputs = build_inputs(
        None,
        DeclaredMetadata(cost_bps_per_side=1),
        report_bytes=report,
        report_filename="mt5_history.html",
        now=NOW,
    )
    result = _run(inputs)
    assert result.reconciliation is not None
    assert result.reconciliation["status"] == "CONTRADICTION"
    assert result.reconciliation["difference"]["value"] == pytest.approx(9.83)
    assert result.forensics is not None
    assert any(
        check["id"] == "BALANCE_CHAIN"
        and any(figure[:2] == ["n_hits", "2"] for figure in check["figures"])
        for check in result.forensics["checks"]
    )
    assert ("MONETARY_RECONCILIATION_MISMATCH", "FAIL") in {
        (flag["code"], flag["severity"]) for flag in result.red_flags
    }
