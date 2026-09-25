"""Challenge presets carry their source and date and validate their rules."""

from __future__ import annotations

import re

import pytest

from quant_trade.audit.prop_presets import DEFAULT_PRESET, PRESETS, ChallengeRules, get_preset


def test_default_preset_matches_the_plan() -> None:
    rules = get_preset(DEFAULT_PRESET)
    assert (rules.profit_target, rules.max_daily_loss, rules.max_total_loss) == (0.10, 0.05, 0.10)
    assert rules.total_loss_type == "static"
    assert rules.min_trading_days == 4
    assert rules.time_limit_days is None


def test_required_firms_are_present() -> None:
    firms = {rules.firm for rules in PRESETS.values()}
    assert {"FTMO", "FundedNext", "The5ers", "Topstep"} <= firms


@pytest.mark.parametrize("key", sorted(PRESETS))
def test_every_preset_is_sourced_and_dated(key: str) -> None:
    rules = PRESETS[key]
    assert rules.key == key
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", rules.as_of)
    if rules.firm != "Generic":
        assert rules.source_url.startswith("https://")
    assert rules.notes
    assert rules.to_dict()["notes"] == list(rules.notes)


def test_topstep_limits_in_dollars() -> None:
    assert PRESETS["topstep-50k-combine"].max_total_loss * 50_000 == pytest.approx(2_000)
    assert PRESETS["topstep-100k-combine"].max_total_loss * 100_000 == pytest.approx(3_000)
    assert PRESETS["topstep-150k-combine"].profit_target * 150_000 == pytest.approx(9_000)


def test_unknown_preset_lists_the_valid_names() -> None:
    with pytest.raises(KeyError, match="ftmo-2step-phase1"):
        get_preset("nope")


def test_invalid_rules_are_refused() -> None:
    base = get_preset(DEFAULT_PRESET).to_dict()
    base["notes"] = tuple(base["notes"])
    for change in (
        {"profit_target": 10.0},
        {"max_total_loss": 0.0},
        {"daily_loss_basis": "none"},
        {"max_daily_loss": None},
        {"total_loss_type": "intraday"},
        {"min_trading_days": -1},
        {"time_limit_days": 0},
        {"source_url": ""},
    ):
        with pytest.raises(ValueError):
            ChallengeRules(**{**base, **change})


def test_upload_form_shows_when_the_rules_were_read() -> None:
    from quant_trade.audit.guard import find_claims
    from quant_trade.audit.pages import _plain_date, landing
    from quant_trade.audit.prop_presets import AS_OF

    for locale in ("es", "en"):
        html = landing(locale=locale)
        assert _plain_date(AS_OF, locale) in html
    assert _plain_date("2026-09-25", "es") == "25 sep 2026"
    assert _plain_date("2026-09-25", "en") == "Sep 25, 2026"
    for rules in PRESETS.values():
        for note in rules.notes:
            assert find_claims(note) == []
