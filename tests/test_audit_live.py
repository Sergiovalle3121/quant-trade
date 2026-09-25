"""A live account statement compared with its backtest (``audit/live.py``)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from quant_trade.audit import live as live_lib
from quant_trade.audit.guard import find_claims
from quant_trade.audit.i18n import localize
from quant_trade.audit.live import compare_live
from quant_trade.audit.report import LABELS
from quant_trade.audit.schema import ParsedTrades
from quant_trade.core.models import Trade


def _trades(
    pnl: list[float],
    *,
    start: datetime = datetime(2023, 1, 2, tzinfo=UTC),
    size: float = 1.0,
    every: timedelta = timedelta(days=1),
) -> ParsedTrades:
    rows = [
        Trade(
            entry_time=start + i * every,
            exit_time=start + i * every + timedelta(hours=3),
            quantity=size,
            entry_price=1.0,
            exit_price=1.0,
            pnl=value,
            return_pct=0.0,
        )
        for i, value in enumerate(pnl)
    ]
    return ParsedTrades(
        trades=rows, sides=["buy"] * len(rows), client_pnl=list(pnl), invalid_rows=0
    )


def _backtest() -> ParsedTrades:
    rng = np.random.default_rng(3)
    return _trades(list(rng.normal(5.0, 40.0, 400).round(2)))


LIVE_START = datetime(2024, 6, 3, tzinfo=UTC)


def test_live_trades_like_the_backtest_are_consistent() -> None:
    rng = np.random.default_rng(4)
    live = _trades(list(rng.normal(5.0, 40.0, 60).round(2)), start=LIVE_START)
    result = compare_live(_backtest(), live)
    assert result["status"] == "MEASURED"
    assert result["outcome"] == live_lib.CONSISTENT
    assert not result["rescaled"] and not result["overlap"]
    assert result["live"]["trades"]["value"] == 60
    assert result["net_below"]["evidence"] == "MEASURED"
    low, high = result["expected"]["net"]["p5"], result["expected"]["net"]["p95"]
    assert low < result["live"]["net"]["value"] < high


def test_a_losing_live_account_is_not_consistent() -> None:
    live = _trades([-30.0] * 40, start=LIVE_START)
    result = compare_live(_backtest(), live)
    assert result["outcome"] == live_lib.INCONSISTENT
    assert result["net_below"]["value"] < live_lib.OUT_TAIL


def test_a_live_result_far_above_the_backtest_asks_a_question() -> None:
    live = _trades([60.0] * 40, start=LIVE_START)
    assert compare_live(_backtest(), live)["outcome"] == live_lib.ABOVE


def test_a_different_size_is_rescaled_to_the_backtest() -> None:
    rng = np.random.default_rng(4)
    pnl = list((rng.normal(5.0, 40.0, 60) / 10).round(4))
    live = _trades(pnl, start=LIVE_START, size=0.1)
    result = compare_live(_backtest(), live)
    assert result["rescaled"] is True
    assert result["size_ratio"]["value"] == pytest.approx(0.1)
    assert result["live"]["net"]["value"] == pytest.approx(sum(pnl) * 10)
    assert result["outcome"] == live_lib.CONSISTENT


def test_itemised_costs_are_subtracted_on_both_sides() -> None:
    backtest = _backtest()
    live = _trades([10.0] * 20, start=LIVE_START)
    charged = ParsedTrades(
        trades=live.trades,
        sides=live.sides,
        client_pnl=live.client_pnl,
        invalid_rows=0,
        fees=[2.0] * 20,
    )
    assert compare_live(backtest, charged)["live"]["net"]["value"] == pytest.approx(160.0)


def test_overlap_pace_and_symbols_are_reported() -> None:
    live = _trades(
        [5.0, -4.0] * 30, start=datetime(2023, 3, 1, tzinfo=UTC), every=timedelta(hours=4)
    )
    result = compare_live(
        _backtest(), live, backtest_symbols=["EURUSD"] * 400, live_symbols=["GBPUSD"] * 60
    )
    assert result["overlap"] is True
    assert result["pace_differs"] is True and result["pace_ratio"]["value"] > 2
    assert result["new_symbols"] == ["GBPUSD"]


@pytest.mark.parametrize(
    ("backtest", "live", "reason"),
    [
        (None, [1.0] * 20, "the backtest has no closed trades"),
        ([1.0] * 10, [1.0] * 20, "the backtest has fewer than 30 closed trades"),
        ([1.0, -1.0] * 50, [1.0] * 5, "the live statement has fewer than 10 closed trades"),
    ],
)
def test_too_little_to_compare_is_not_measured(
    backtest: list[float] | None, live: list[float], reason: str
) -> None:
    result = compare_live(
        _trades(backtest) if backtest is not None else None, _trades(live, start=LIVE_START)
    )
    assert result == {"status": "NOT_MEASURED", "reason": reason}
    assert localize(reason, "es") != reason


def test_the_same_seed_gives_the_same_answer() -> None:
    rng = np.random.default_rng(4)
    live = _trades(list(rng.normal(0.0, 40.0, 500).round(2)), start=LIVE_START)
    first = compare_live(_backtest(), live, seed=9)
    assert first == compare_live(_backtest(), live, seed=9)
    # A long statement is drawn in chunks and still gives every sample.
    assert first["samples"] == live_lib.SAMPLES


def test_live_texts_pass_the_guard_and_have_spanish() -> None:
    for locale in ("es", "en"):
        for key, text in LABELS[locale].items():
            if key.startswith("live"):
                assert find_claims(text) == [], (locale, key)
    assert localize(live_lib.NOTE, "es") != live_lib.NOTE
    assert find_claims(localize(live_lib.NOTE, "es")) == []


def test_the_sample_report_shows_a_live_account() -> None:
    from quant_trade.audit.report import render_html
    from quant_trade.audit.sample import sample_result

    result = sample_result("es", bootstrap_samples=100)
    assert result.live is not None and result.live["status"] == "MEASURED"
    assert result.live["rescaled"] is True and result.live["overlap"] is False
    page = render_html(result, watermark=False)
    assert "Backtest frente a cuenta real" in page
    assert "Cuenta real, a tamaño del backtest" in page
    assert "live account" not in page.lower()
    assert find_claims(page) == []


def test_a_live_statement_is_uploaded_stored_and_shown(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    pytest.importorskip("sqlalchemy")
    from fastapi.testclient import TestClient

    from quant_trade.audit.sample import synthetic_mt5_report
    from quant_trade.audit.settings import AuditSettings
    from quant_trade.audit.store import make_store
    from quant_trade.audit.web import create_app

    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db", bootstrap_samples=100)
    client = TestClient(create_app(settings, make_store(settings.database_url)))
    files = {
        "report": ("ReportTester.html", synthetic_mt5_report(200), "text/html"),
        "live": (
            "ReportHistory.html",
            synthetic_mt5_report(40, seed=5, lots=0.1, start="2024-01-08"),
            "text/html",
        ),
    }
    data = {"consent": "on", "locale": "en"}
    response = client.post("/audits", files=files, data=data, follow_redirects=False)
    assert response.status_code == 303, response.text
    path, _, query = response.headers["location"].partition("?")
    audit_id, token = path.rsplit("/", 1)[1], query.split("token=")[1]
    page = client.get(f"/audits/{audit_id}?token={token}&lang=en")
    assert "Backtest against the live account" in page.text
    assert find_claims(page.text) == []
    body = client.get(f"/audits/{audit_id}.json?token={token}").json()
    assert body["live"]["status"] == "MEASURED"
    assert body["live"]["live"]["trades"]["value"] == 40
    assert "live.html" in body["inputs"]["digests"]
    record = client.app.state.store.get_audit(audit_id, with_blobs=True)  # type: ignore[attr-defined]
    assert set(record.files) == {"report.html", "live.html"}


def test_the_upload_form_offers_a_live_statement() -> None:
    from quant_trade.audit.pages import landing

    assert "name='live'" in landing(locale="es") and "cuenta real" in landing(locale="es")
    assert "name='live'" in landing(locale="en") and "Live or demo" in landing(locale="en")
