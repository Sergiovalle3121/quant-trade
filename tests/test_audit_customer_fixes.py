"""What a first-time customer tripped over, kept fixed."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from audit_fixtures import csv_bytes, positive_drift, variants_bytes

from quant_trade.audit.engine import run_audit, trial_count
from quant_trade.audit.guard import find_claims
from quant_trade.audit.prop_presets import PRESETS, preset_label
from quant_trade.audit.redflags import FLAG_TITLES
from quant_trade.audit.report import _fmt, _prefilled, _short_time, render_html
from quant_trade.audit.schema import NOT_MEASURED, DeclaredMetadata, build_inputs

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _inputs(declared: DeclaredMetadata, *, variants: bool = False):
    matrix = np.random.default_rng(3).normal(0.0005, 0.01, size=(300, 12))
    return build_inputs(
        csv_bytes(positive_drift(300)),
        declared,
        variants_bytes=variants_bytes(matrix) if variants else None,
    )


def test_trials_left_blank_are_assumed_not_declared() -> None:
    inputs = _inputs(DeclaredMetadata(trials=1, trials_declared=False), variants=True)
    result = run_audit(inputs, now=NOW, audit_id="t1", bootstrap_samples=50)
    codes = {flag["code"] for flag in result.red_flags}
    assert "TRIALS_BELOW_VARIANTS" not in codes
    blank = trial_count(_inputs(DeclaredMetadata(trials=1, trials_declared=False)))
    assert blank[1] == NOT_MEASURED
    declared = run_audit(
        _inputs(DeclaredMetadata(trials=1), variants=True),
        now=NOW,
        audit_id="t2",
        bootstrap_samples=50,
    )
    assert "TRIALS_BELOW_VARIANTS" in {flag["code"] for flag in declared.red_flags}


def test_generic_preset_shows_no_internal_path_and_no_repeated_phase() -> None:
    generic = next(r for r in PRESETS.values() if r.firm == "Generic")
    label = preset_label(generic.firm, generic.program, generic.phase, "es")
    assert label.count("1") <= 1
    for rules in PRESETS.values():
        assert preset_label(rules.firm, rules.program, rules.phase, "en")
    inputs = build_inputs(
        csv_bytes(positive_drift(300)),
        DeclaredMetadata(challenge=next(k for k, r in PRESETS.items() if r.firm == "Generic")),
    )
    page = render_html(
        run_audit(inputs, now=NOW, audit_id="t3", bootstrap_samples=50), watermark=False
    )
    assert "docs/" not in page
    assert "Reglas de referencia genéricas" in page


def test_locked_report_links_to_unlock_and_asks_to_keep_the_link() -> None:
    result = run_audit(
        _inputs(DeclaredMetadata(trials=2)), now=NOW, audit_id="t4", bootstrap_samples=50
    )
    page = render_html(
        result,
        watermark=True,
        free_mode=False,
        redeem_url="/r",
        contact_url="https://wa.me/5215550000000",
    )
    assert "href='#unlock'" in page and "id='unlock'" in page
    assert "Guarda el enlace" in page
    assert "https://wa.me/5215550000000?text=" in page and "t4" in page
    # No trades were uploaded: the lock list does not sell what was not measured.
    lock = page.split("id='unlock'")[1].split("</ul>")[0]
    assert "Estadísticas de las operaciones" not in lock
    assert "Plan para subir de clase" in lock or "<li>" in lock
    assert find_claims(page) == []


def test_small_display_fixes() -> None:
    assert _prefilled("https://example.com/buy", "hola") == "https://example.com/buy"
    assert _prefilled("https://wa.me/1?text=x", "hola") == "https://wa.me/1?text=x"
    assert _prefilled("https://wa.me/1", "a b") == "https://wa.me/1?text=a%20b"
    assert _short_time("2026-09-24T19:40:12.123456Z") == "2026-09-24 19:40 UTC"
    assert _fmt(12.0) == "12"
    assert _fmt(0.1234) == "0.1234"


@pytest.mark.parametrize("path", ["/", "/en"])
def test_landing_counts_every_red_flag(tmp_path: Path, path: str) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from quant_trade.audit.settings import AuditSettings
    from quant_trade.audit.store import make_store
    from quant_trade.audit.web import create_app

    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/a.db")
    client = TestClient(create_app(settings, make_store(settings.database_url)))
    page = client.get(path).text
    assert f"{len(FLAG_TITLES)} " in page
    assert "Catorce" not in page and "Fourteen" not in page
    blank = client.post(
        "/audits",
        files={"equity": ("e.csv", csv_bytes(positive_drift(200)), "text/csv")},
        data={"consent": "on", "trials": "", "cost_bps": ""},
        follow_redirects=False,
    )
    assert blank.status_code == 303


def test_short_histories_do_not_get_an_annual_return() -> None:
    short = run_audit(
        build_inputs(csv_bytes(positive_drift(40)), DeclaredMetadata()),
        now=NOW,
        audit_id="c1",
        bootstrap_samples=50,
    )
    assert short.performance["cagr"]["evidence"] == NOT_MEASURED
    assert "menos de un año" in render_html(short, watermark=False)
    long = run_audit(
        build_inputs(csv_bytes(positive_drift(400)), DeclaredMetadata()),
        now=NOW,
        audit_id="c2",
        bootstrap_samples=50,
    )
    assert long.performance["cagr"]["evidence"] != NOT_MEASURED


def test_spanish_reports_carry_no_internal_keys() -> None:
    from audit_fixtures import synthetic_mt5_report

    inputs = build_inputs(
        None,
        DeclaredMetadata(trials=3),
        report_bytes=synthetic_mt5_report(),
        report_filename="r.html",
    )
    page = render_html(
        run_audit(inputs, now=NOW, audit_id="k1", bootstrap_samples=50), watermark=False
    )
    for key in (
        "sharpe_per_period",
        "trials_used",
        "break_even_bps",
        "dataset_digest",
        "mt5_tester_html",
        "method=",
        "variance policy",
        "psr_pass=",
        "daily_trading",
        "source=",
        ">skewness<",
        "samples=",
    ):
        assert key not in page.split("<script")[0].replace("id='", ""), key
