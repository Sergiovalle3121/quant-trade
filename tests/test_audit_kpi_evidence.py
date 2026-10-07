"""Headline tiles preserve provenance and keep locked figures concealed."""

import re
from copy import deepcopy

import pytest

from quant_trade.audit.guard import find_claims
from quant_trade.audit.report import (
    LABELS,
    _kpi_evidence,
    _kpi_list,
    _kpis_html,
    _pdf_cover,
    evidence_label,
    localize_text_nodes,
)


def _data():
    def measured(value):
        return {"evidence": "MEASURED", "value": value}

    return {
        "inputs": {"balance_only": False},
        "performance": {
            "total_return": measured(0.05),
            "max_drawdown": measured(-0.1),
            "platform_equity_drawdown": {"evidence": "DECLARED", "value": -0.3},
            "sharpe": measured(1.2),
        },
        "trade_stats": {
            "profit_factor": measured(1.3),
            "trade_count": measured(20),
            "win_rate": measured(0.5),
        },
        "costs": {
            "break_even_bps": measured(5),
            "break_even_pips": measured(1.5),
            "reference_bps": {"evidence": "DECLARED", "value": 2},
        },
        "risk": {"max_drawdown": {"p95": measured(0.18)}},
        "stress": {
            "trades": {
                "original": measured(12),
                "rows": [{"scenario": "best_5_trades", "result": measured(10)}],
            },
            "returns": {
                "original": measured(0.05),
                "rows": [{"scenario": "best_5_periods", "result": measured(0.01)}],
            },
        },
    }


def _tiles(markup):
    return re.findall(r"<div class='kpi [^']*'>(.*?)</div>", markup, re.DOTALL)


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_all_headline_tiles_have_localized_provenance_and_keep_values(locale):
    data = _data()
    original = deepcopy(data)
    figures = _kpi_list(data, LABELS[locale])
    body = localize_text_nodes(_kpis_html(data, LABELS[locale], locked=False), locale)
    tiles = _tiles(body)
    assert len(tiles) == len(figures) == 10
    for tile, (label, shown, _) in zip(tiles, figures, strict=True):
        expected = "DECLARED" if label == LABELS[locale]["kpi_dd_platform"] else "MEASURED"
        assert f"<b>{shown}</b>" in tile
        assert tile.count('class="badge ') == 1
        assert f'class="badge {expected}">{evidence_label(expected, locale)}</span>' in tile
    assert data == original
    assert find_claims(body) == []


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_composite_tiles_include_every_displayed_numeric_source(locale):
    data = _data()
    data["trade_stats"]["win_rate"]["evidence"] = "DECLARED"
    data["costs"]["break_even_pips"]["evidence"] = "DECLARED"
    data["stress"]["trades"]["original"]["evidence"] = "DECLARED"
    original = deepcopy(data)
    labels = LABELS[locale]
    figures = _kpi_list(data, labels)
    by_label = {label: _kpi_evidence(label, labels, data) for label, _, _ in figures}
    assert by_label[labels["kpi_trades"]] == "DECLARED"
    assert by_label[labels["kpi_stress"]] == "DECLARED"
    costs = [label for label in by_label if label.startswith(labels["kpi_breakeven"] + " (")]
    assert len(costs) == 1 and by_label[costs[0]] == "DECLARED"
    data["costs"]["break_even_bps"]["value"] = 0
    zero_label = next(
        label
        for label, _, _ in _kpi_list(data, labels)
        if label.startswith(labels["kpi_breakeven"] + " (")
    )
    assert _kpi_evidence(zero_label, labels, data) == "MEASURED"
    data["costs"]["break_even_bps"]["value"] = original["costs"]["break_even_bps"]["value"]
    assert data == original


@pytest.mark.parametrize("tag", [None, "UNKNOWN", "NOT_MEASURED"])
def test_unknown_provenance_is_never_upgraded_to_measured(tag):
    data = _data()
    data["performance"]["sharpe"]["evidence"] = tag
    assert _kpi_evidence(LABELS["es"]["kpi_sharpe"], LABELS["es"], data) == "NOT_MEASURED"


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_pdf_cover_keeps_the_provenance_of_its_four_headline_figures(locale):
    data = _data()
    data.update(audit_id="synthetic", generated_at_utc="2026-10-06T00:00:00Z")
    verdict = {"overall": "C", "summary": "Synthetic QA.", "dimensions": []}
    original = deepcopy(data)
    cover = localize_text_nodes(_pdf_cover(data, verdict, LABELS[locale]), locale)
    assert cover.count('class="badge MEASURED"') == 3
    assert cover.count('class="badge DECLARED"') == 1
    assert f'class="badge DECLARED">{evidence_label("DECLARED", locale)}</span>' in cover
    assert data == original


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
@pytest.mark.parametrize("break_even_bps", [5, 0, -5])
def test_locked_tiles_keep_figures_and_provenance_concealed(locale, break_even_bps):
    data = _data()
    data["costs"]["break_even_bps"]["value"] = break_even_bps
    original = deepcopy(data)
    body = _kpis_html(data, LABELS[locale], locked=True)
    assert body.count("class='kpi locked'") == 10
    assert 'class="badge ' not in body
    assert "<b>1.20</b>" not in body and "<b>-30.0%</b>" not in body
    assert "1.5 pips" not in body
    label = LABELS[locale]["kpi_breakeven"]
    assert f"aria-label='{label}: " in body and f"<span>{label}</span>" in body
    assert label + " (" not in body
    assert data == original
