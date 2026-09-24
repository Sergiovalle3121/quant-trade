"""Iteration 4 wired together: platform reports, measured trials, trade
statistics, resampled risk, the challenge simulator and the report around them."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from audit_fixtures import (
    best_of_n_walks,
    csv_bytes,
    positive_drift,
    synthetic_mt5_optimization,
    synthetic_mt5_report,
    trades_following,
    trades_frame,
    variants_bytes,
)
from typer.testing import CliRunner

from quant_trade.audit import redflags
from quant_trade.audit.engine import WITHHELD_TEXT, run_audit, trial_count
from quant_trade.audit.guard import find_claims
from quant_trade.audit.prop_presets import DEFAULT_PRESET
from quant_trade.audit.report import render, render_html
from quant_trade.audit.schema import (
    SCHEMA_VERSION,
    AuditResult,
    DeclaredMetadata,
    ParseError,
    build_inputs,
    report_digest_name,
)
from quant_trade.audit.verdict import DIMENSION_ORDER, MEANING, meaning
from quant_trade.cli import app

NOW = datetime(2026, 1, 1, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1]


def _run(inputs, **kw):
    return run_audit(
        inputs,
        now=NOW,
        audit_id="it4",
        bootstrap_samples=200,
        risk_samples=300,
        challenge_samples=500,
        **kw,
    )


def _mt5_inputs(**declared):
    return build_inputs(
        None,
        DeclaredMetadata(cost_bps_per_side=1, **declared),
        report_bytes=synthetic_mt5_report(edge_pips=8.0),
        report_filename="ReportTester-123.html",
    )


def _status(result: AuditResult, name: str) -> str:
    return {d.name: d.status for d in result.verdict.dimensions}[name]


# -- inputs -------------------------------------------------------------------


def test_an_mt5_report_alone_gives_trades_and_a_balance_curve() -> None:
    inputs = _mt5_inputs()
    assert inputs.source_format == "mt5_tester_html"
    assert inputs.balance_only is True
    assert inputs.trades is not None and len(inputs.trades.trades) == 400
    assert inputs.trade_symbols == ["EURUSD"] * 400
    assert inputs.reported_fees["commission"] == pytest.approx(-2800.0)
    assert inputs.initial_balance == 10_000.0
    assert set(inputs.digests) == {"report.html"}
    assert any("floating" in warning for warning in inputs.warnings)


def test_report_digest_names_keep_only_known_extensions() -> None:
    assert report_digest_name("a.HTM") == "report.htm"
    assert report_digest_name("list.xlsx") == "report.xlsx"
    assert report_digest_name("x.exe") == "report.bin"
    assert report_digest_name(None) == "report.bin"


def test_report_and_trades_file_together_are_refused() -> None:
    with pytest.raises(ParseError) as caught:
        build_inputs(
            None,
            DeclaredMetadata(),
            report_bytes=synthetic_mt5_report(days=40),
            trades_bytes=csv_bytes(trades_frame(5)),
        )
    assert caught.value.code == "trades_and_report"
    assert "no ambos" in caught.value.localized("es")


def test_nothing_to_audit_is_a_localized_error() -> None:
    with pytest.raises(ParseError) as caught:
        build_inputs(None, DeclaredMetadata())
    assert caught.value.code == "equity_required"
    assert caught.value.localized("es").startswith("Hace falta")


def test_an_uploaded_equity_curve_wins_over_the_report_balance() -> None:
    frame = positive_drift(400)
    inputs = build_inputs(
        csv_bytes(frame),
        DeclaredMetadata(),
        report_bytes=synthetic_mt5_report(days=60),
        report_filename="r.html",
    )
    assert inputs.balance_only is False
    assert inputs.equity.observations == 400
    assert set(inputs.digests) == {"equity.csv", "report.html"}


def test_unknown_challenge_preset_is_refused() -> None:
    with pytest.raises(ValueError):
        DeclaredMetadata(challenge="no-such-firm")
    assert DeclaredMetadata(challenge="  ").challenge is None


# -- the number of trials -----------------------------------------------------


def test_optimisation_passes_become_the_measured_trial_count() -> None:
    inputs = build_inputs(
        None,
        DeclaredMetadata(trials=1, cost_bps_per_side=1),
        report_bytes=synthetic_mt5_report(edge_pips=8.0),
        report_filename="r.html",
        optimization_bytes=synthetic_mt5_optimization(250),
    )
    assert trial_count(inputs) == (250, "MEASURED", "passes in the MT5 optimisation export")
    result = _run(inputs)
    multiplicity = result.multiplicity
    assert multiplicity["trials_used"]["value"] == 250
    assert multiplicity["trials_used"]["evidence"] == "MEASURED"
    assert multiplicity["dsr_at_trials_used"]["value"] < multiplicity["dsr_at_declared"]["value"]
    assert result.inputs["optimization"]["passes"]["value"] == 250
    assert "optimization.xml" in result.inputs["digests"]
    codes = {flag["code"] for flag in result.red_flags}
    assert "TRIALS_BELOW_VARIANTS" in codes
    dimension = next(d for d in result.verdict.dimensions if d.name == "multiplicity")
    assert dimension.inputs["trials_used"]["evidence"] == "MEASURED"
    assert "250" in result.verdict.summary


def test_best_of_100_walks_declared_as_one_trial_is_not_rescued_by_the_declaration() -> None:
    """The defect: variants uploaded, one trial declared, the class used to be B."""
    winner, matrix = best_of_n_walks(trials=100, n=512)
    inputs = build_inputs(
        csv_bytes(winner),
        DeclaredMetadata(trials=1, cost_bps_per_side=5),
        variants_bytes=variants_bytes(matrix),
    )
    result = _run(inputs)
    assert result.multiplicity["trials_used"] == {
        "value": 100,
        "evidence": "MEASURED",
        "note": "columns of the uploaded variants matrix",
    }
    assert _status(result, "multiplicity") in {"WEAK", "FAIL"}
    assert result.verdict.overall in {"C", "D"}


def test_a_larger_declaration_stays_declared() -> None:
    winner, matrix = best_of_n_walks(trials=20, n=256)
    inputs = build_inputs(
        csv_bytes(winner),
        DeclaredMetadata(trials=500),
        variants_bytes=variants_bytes(matrix),
    )
    assert trial_count(inputs) == (500, "DECLARED", "declared by the client")


# -- trades against the curve -------------------------------------------------


def test_unrelated_trades_are_flagged_and_matching_trades_are_not() -> None:
    frame = positive_drift(1500)
    unrelated = build_inputs(
        csv_bytes(frame), DeclaredMetadata(), trades_bytes=csv_bytes(trades_frame(60))
    )
    matching = build_inputs(
        csv_bytes(frame), DeclaredMetadata(), trades_bytes=csv_bytes(trades_following(frame))
    )
    assert unrelated.trades is not None and matching.trades is not None
    codes = {f.code for f in redflags.scan_trades_against_equity(unrelated.trades, frame)}
    assert codes == {"TRADES_EQUITY_UNRELATED"}
    assert redflags.scan_trades_against_equity(matching.trades, frame) == []
    result = _run(unrelated)
    assert _status(result, "data_quality") == "WEAK"


def test_trades_outside_the_curve_dates_are_flagged() -> None:
    frame = positive_drift(200)
    trades = build_inputs(
        csv_bytes(positive_drift(1500)),
        DeclaredMetadata(),
        trades_bytes=csv_bytes(trades_frame(40)),
    ).trades
    assert trades is not None
    flags = redflags.scan_trades_against_equity(trades, frame)
    assert "TRADES_OUTSIDE_EQUITY" in {flag.code for flag in flags}


def test_every_red_flag_code_has_a_title_in_both_languages() -> None:
    source = (ROOT / "src/quant_trade/audit/redflags.py").read_text(encoding="utf-8")
    codes = set(re.findall(r'"([A-Z][A-Z_]{5,})",\n\s+"(?:FAIL|WARN)', source))
    codes |= set(re.findall(r'RedFlag\("([A-Z_]+)"', source))
    assert codes, "no flag codes found"
    assert codes <= set(redflags.FLAG_TITLES)
    for titles in redflags.FLAG_TITLES.values():
        assert set(titles) == {"es", "en"}
        assert find_claims(" ".join(titles.values())) == []


# -- the result ---------------------------------------------------------------


def test_the_result_carries_series_trade_stats_risk_and_challenge() -> None:
    result = _run(_mt5_inputs(challenge="ftmo-2step-phase1"))
    assert result.schema_version == SCHEMA_VERSION == 2
    assert result.inputs["source_format"] == "mt5_tester_html"
    assert result.inputs["balance_only"] is True
    series = result.series
    assert series is not None and series["evidence"] == "MEASURED"
    assert len(series["timestamps"]) == len(series["equity"]) <= 400
    assert len(series["month_end_timestamps"]) >= 18
    assert result.trade_stats is not None and result.trade_stats["status"] == "MEASURED"
    assert result.trade_stats["trade_count"]["value"] == 400
    assert result.trade_stats["fees_total"]["value"] == pytest.approx(2800.0)
    assert result.risk is not None and result.risk["status"] == "MEASURED"
    assert result.risk["max_drawdown"]["p95"]["evidence"] == "MEASURED"
    challenge = result.challenge
    assert challenge is not None and challenge["status"] == "MEASURED"
    assert challenge["preset"] == "ftmo-2step-phase1"
    assert challenge["selected_by"] == "client"
    total = sum(item["value"] for item in challenge["probability"].values())
    assert total == pytest.approx(1.0)
    assert result.vendor_questions
    assert all(set(q) == {"code", "es", "en"} for q in result.vendor_questions)


def test_the_default_challenge_preset_is_recorded_as_default() -> None:
    result = _run(_mt5_inputs())
    assert result.challenge is not None
    assert result.challenge["preset"] == DEFAULT_PRESET
    assert result.challenge["selected_by"] == "default"


def test_monthly_data_cannot_feed_the_challenge_simulator() -> None:
    stamps = __import__("pandas").date_range("2010-01-31", periods=120, freq="ME", tz="UTC")
    frame = positive_drift(120).assign(timestamp=stamps)
    result = _run(build_inputs(csv_bytes(frame), DeclaredMetadata()))
    assert result.challenge is not None and result.challenge["status"] == "NOT_MEASURED"
    assert "daily" in result.challenge["reason"]


def test_the_audit_is_deterministic() -> None:
    first = _run(_mt5_inputs()).model_dump(mode="json")
    second = _run(_mt5_inputs()).model_dump(mode="json")
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_promotional_report_metadata_is_withheld() -> None:
    inputs = _mt5_inputs()
    object.__setattr__(
        inputs, "report_metadata", {"strategy": "Guaranteed returns EA", "symbol": "EURUSD"}
    )
    result = _run(inputs)
    assert result.inputs["report_metadata"] == {"strategy": WITHHELD_TEXT, "symbol": "EURUSD"}
    html_text, _ = render(result, watermark=True)
    assert "Guaranteed" not in html_text


def test_a_schema_1_result_still_loads_and_renders() -> None:
    payload = _run(build_inputs(csv_bytes(positive_drift(300)), DeclaredMetadata())).model_dump(
        mode="json"
    )
    for key in ("series", "trade_stats", "risk", "challenge", "vendor_questions"):
        payload.pop(key)
    payload["schema_version"] = 1
    for dimension in payload["verdict"]["dimensions"]:
        dimension.pop("reasons_es")
    old = AuditResult.model_validate(payload)
    html_text, _ = render(old, watermark=True)
    assert "Qué significa para ti" in html_text


# -- plain language and the report --------------------------------------------


def test_every_dimension_and_status_has_two_plain_sentences_that_pass_the_guard() -> None:
    statuses = ("PASS", "WEAK", "FAIL", "NOT_MEASURED")
    for locale in ("es", "en"):
        for name in DIMENSION_ORDER:
            for status in statuses:
                if name == "data_quality" and status == "NOT_MEASURED":
                    continue  # data quality is always measured
                text = meaning(name, status, locale)
                assert text, (locale, name, status)
                assert text.count(". ") + text.count(": ") >= 1
        assert find_claims(" ".join(MEANING[locale].values())) == []
    assert meaning("benchmark", "NOT_APPLICABLE", "en")


def test_spanish_reports_give_spanish_reasons() -> None:
    result = _run(build_inputs(csv_bytes(positive_drift(400)), DeclaredMetadata(locale="es")))
    by_name = {d.name: d for d in result.verdict.dimensions}
    assert by_name["benchmark"].reasons_in("es") == ["no se subió un benchmark"]
    assert by_name["benchmark"].reasons_in("en") == ["no benchmark uploaded"]
    assert "no benchmark uploaded" not in result.verdict.summary
    assert "no se subió un benchmark" in result.verdict.summary
    html_text = render_html(result, watermark=False)
    assert "no se declaró un inicio fuera de muestra" in html_text


@pytest.mark.parametrize("locale", ["es", "en"])
def test_the_full_report_has_charts_explanations_and_print(locale: str) -> None:
    result = _run(_mt5_inputs(locale=locale))
    html_text, _ = render(result, watermark=False)
    assert html_text.count("<svg") >= 3  # equity, drawdown, fan
    assert 'class="monthly"' in html_text
    assert "window.print()" in html_text
    assert "@media print" in html_text
    assert "<script" not in html_text.lower()
    heading = "Qué significa para ti" if locale == "es" else "What this means for you"
    assert heading in html_text
    challenge_title = "Simulador de reto" if locale == "es" else "Prop-firm challenge simulator"
    assert challenge_title in html_text
    assert "ftmo.com" not in html_text or "2026-09-24" in html_text
    assert find_claims(html_text) == []


def test_locked_report_keeps_verdict_charts_and_meaning_but_sends_no_detail() -> None:
    result = _run(_mt5_inputs())
    unpaid = render_html(result, watermark=True, free_mode=False, checkout_url="/pay")
    paid = render_html(result, watermark=False, free_mode=False)
    assert "<svg" in unpaid and "Qué significa para ti" in unpaid
    assert result.verdict.summary[:50] in unpaid
    stats = result.trade_stats
    assert stats is not None
    factor = f"{stats['profit_factor']['value']:.4f}"
    assert factor in paid and factor not in unpaid
    probability = result.challenge["probability"]["pass"]["value"]  # type: ignore[index]
    assert f"{probability:.2%}" in paid
    assert "Llega al objetivo" in paid and "Llega al objetivo" not in unpaid
    assert "Estadísticas de las operaciones" in unpaid  # listed as a locked title
    assert "/pay" in unpaid


# -- CLI ----------------------------------------------------------------------


def test_cli_runs_a_platform_report_with_optimisation_and_challenge(tmp_path: Path) -> None:
    report = tmp_path / "ReportTester.html"
    optimization = tmp_path / "opt.xml"
    report.write_bytes(synthetic_mt5_report())
    optimization.write_bytes(synthetic_mt5_optimization(40))
    out = tmp_path / "out"
    result = CliRunner().invoke(
        app,
        [
            "audit",
            "run",
            "--report",
            str(report),
            "--optimization",
            str(optimization),
            "--challenge",
            "the5ers-high-stakes-step1",
            "--output-dir",
            str(out),
            "--bootstrap-samples",
            "100",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads((out / "audit.json").read_text(encoding="utf-8"))
    assert payload["inputs"]["source_format"] == "mt5_tester_html"
    assert payload["multiplicity"]["trials_used"]["value"] == 40
    assert payload["challenge"]["preset"] == "the5ers-high-stakes-step1"
    assert (out / "report.html").exists()


def test_cli_needs_equity_or_report_and_a_known_preset(tmp_path: Path) -> None:
    runner = CliRunner()
    missing = runner.invoke(app, ["audit", "run", "--output-dir", str(tmp_path)])
    assert missing.exit_code != 0
    report = tmp_path / "r.html"
    report.write_bytes(synthetic_mt5_report(days=40))
    unknown = runner.invoke(
        app,
        ["audit", "run", "--report", str(report), "--challenge", "nope", "--output-dir", "x"],
    )
    assert unknown.exit_code != 0


def test_cli_lists_presets_with_source_and_date() -> None:
    result = CliRunner().invoke(app, ["audit", "presets"])
    assert result.exit_code == 0, result.output
    assert DEFAULT_PRESET in result.output
    assert "ftmo-2step-phase1" in result.output
    assert "2026-09-24" in result.output


def test_mt5_commission_is_measured_not_replaced_by_the_zero_cost_assumption() -> None:
    inputs = build_inputs(
        None,
        DeclaredMetadata(),
        report_bytes=synthetic_mt5_report(edge_pips=8.0),
        report_filename="Report.html",
    )
    assert inputs.trades is not None and inputs.trades.reports_fees
    assert sum(inputs.trades.fees or []) == pytest.approx(2800.0)
    result = _run(inputs)
    costs = result.costs
    assert costs["reported_costs_in_rows"] is True
    assert costs["reference_bps"]["value"] == pytest.approx(0.5)
    assert "slippage" in costs["reference_bps"]["note"]
    zero = costs["rows"][0]
    # The 0x row is the report's own net: gross minus the commission it charged
    # (gross recomputed from the rounded prices, so within a dollar).
    assert result.trade_stats is not None
    assert zero["net_pnl"]["value"] == pytest.approx(
        result.trade_stats["net_pnl"]["value"], abs=1.0
    )
    assert zero["total_cost"]["value"] == pytest.approx(2800.0)
    codes = {flag["code"] for flag in result.red_flags}
    assert "ZERO_DECLARED_COSTS" not in codes


def test_a_csv_trade_list_without_fees_keeps_the_ten_bps_reference() -> None:
    frame = positive_drift(500)
    inputs = build_inputs(
        csv_bytes(frame), DeclaredMetadata(), trades_bytes=csv_bytes(trades_following(frame))
    )
    result = _run(inputs)
    assert result.costs["reference_bps"]["value"] == pytest.approx(10.0)
    assert result.costs["reported_costs_in_rows"] is False
    assert "ZERO_DECLARED_COSTS" in {flag["code"] for flag in result.red_flags}
