"""Independent arithmetic, evidence, translations and active-content boundaries."""

from __future__ import annotations

from dataclasses import replace
from xml.etree import ElementTree as ET

import pytest

from quant_trade.audit.calculator import CalculatorInput, compute
from quant_trade.audit.guard import find_claims
from quant_trade.audit.public_card import COPY, PublicClaim, _readings, _wilson, public_card_svg

NS = {"s": "http://www.w3.org/2000/svg"}
FULL = PublicClaim(
    source_handle="@example",
    source_url="https://example.org/post/123",
    trades=45,
    win_rate=0.71,
    profit_factor=3.24,
    sharpe=1.9,
    years=3,
    trials=100,
    target_r=2,
    stop_r=1,
)


def test_hand_checked_arithmetic_preserves_the_declared_rate() -> None:
    # Wilson on p=.71, not the invented integer count round(.71*45).
    assert _wilson(0.71, 45) == pytest.approx((0.56515869, 0.82180764), abs=1e-8)
    results = {key: value for key, value, _ in _readings(replace(FULL, locale="en"))}
    assert results == {
        "wilson": "56.5 % – 82.2 %",
        "coin": "N=20: 64.2 % · N=100: 68.9 %",
        "luck": "≈ 1.47",
        "breakeven": "33.3 %",
    }


@pytest.mark.parametrize(("locale", "mark"), [("es", ","), ("en", "."), ("pt", ",")])
def test_card_figures_use_the_languages_decimal_mark(locale: str, mark: str) -> None:
    """The same values in each language's typography: a decimal comma in es and pt."""
    claim = replace(FULL, locale=locale)  # type: ignore[arg-type]
    results = {key: value for key, value, _ in _readings(claim)}
    assert results == {
        "wilson": f"56{mark}5 % – 82{mark}2 %",
        "coin": f"N=20: 64{mark}2 % · N=100: 68{mark}9 %",
        "luck": f"≈ 1{mark}47",
        "breakeven": f"33{mark}3 %",
    }
    root = ET.fromstring(public_card_svg(claim))
    shown = {
        node.attrib["data-field"]: [text.text for text in node.findall("s:text", NS)][1]
        for node in root.iter("{http://www.w3.org/2000/svg}g")
        if "data-field" in node.attrib
    }
    assert shown["win_rate"] == f"71{mark}0 %"
    assert shown["profit_factor"] == f"3{mark}24"
    assert shown["sharpe"] == f"1{mark}9"
    assert shown["trades"] == "45" and shown["trials"] == "100"
    other = "." if mark == "," else ","
    for key, value in results.items():
        assert other not in value, key


@pytest.mark.parametrize("sharpe", [0.5, 1.9, 4.0])
def test_sharpe_reuses_the_calculators_account(sharpe: float) -> None:
    claim = replace(FULL, sharpe=sharpe, locale="en")
    expected = compute(CalculatorInput(sharpe=sharpe, years=3, trials=100))
    assert _readings(claim)[2][1] == f"≈ {expected['luck_sharpe']['value']:.2f}"


def test_luck_without_declared_sharpe_discloses_null_dispersion() -> None:
    result = _readings(PublicClaim(years=3, trials=100))[2]
    assert result[1] == "≈ 1,46"  # 2.530602894 / sqrt(755) * sqrt(252), in Spanish.
    assert COPY["es"]["null_note"] in result[2]
    assert _readings(PublicClaim(years=3, trials=1, locale="en"))[2][1] == "≈ 0.00"


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
@pytest.mark.parametrize(
    "claim", [FULL, PublicClaim(), PublicClaim(trades=5, years=0.01, trials=2)]
)
def test_translations_accessibility_evidence_and_guard(locale: str, claim: PublicClaim) -> None:
    svg = public_card_svg(replace(claim, locale=locale))
    root = ET.fromstring(svg)
    assert (root.get("width"), root.get("height")) == ("1200", "675")
    assert root.get("viewBox") == "0 0 1200 675"
    assert root.get("role") == "img"
    assert root.find("s:title", NS) is not None
    assert root.find("s:desc", NS) is not None
    assert find_claims(" ".join(root.itertext())) == []
    assert find_claims(" ".join(COPY[locale].values())) == []
    assert root.findall(".//s:script", NS) == []
    assert not any(key.lower().startswith("on") for node in root.iter() for key in node.attrib)
    fields = root.findall(".//s:g[@data-field]", NS)
    readings = root.findall(".//s:g[@data-reading]", NS)
    assert len(fields) == 8 and len(readings) == 4
    for node in fields + readings:
        assert node.get("data-evidence") in ("DECLARED", "NOT_MEASURED")
        assert node.get("data-evidence") in " ".join(node.itertext())
    assert COPY[locale]["footer"] in svg and COPY[locale]["cta"] in svg
    assert 'data-evidence="MEASURED"' not in svg


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_missing_readings_all_explain_the_absent_inputs(locale: str) -> None:
    root = ET.fromstring(public_card_svg(PublicClaim(locale=locale)))
    for node in root.findall(".//s:g[@data-reading]", NS):
        assert node.get("data-evidence") == "NOT_MEASURED"
        reason = COPY[locale][node.attrib["data-reading"] + "_missing"]
        assert reason in " ".join(node.itertext())


@pytest.mark.parametrize(
    ("locale", "fallback"),
    [
        ("es", "Cifras declaradas por quien usó la herramienta"),
        ("en", "Figures declared by the person who used the tool"),
        ("pt", "Números declarados por quem usou a ferramenta"),
    ],
)
@pytest.mark.parametrize(
    ("handle", "url"),
    [
        ("@example", "https://example.org/post/123"),
        ("@example", ""),
        ("", "https://example.org/post/123"),
        ("", ""),
        (" ", " "),
    ],
)
def test_only_present_sources_or_one_fixed_attribution_are_shown(
    locale: str, fallback: str, handle: str, url: str
) -> None:
    svg = public_card_svg(PublicClaim(locale=locale, source_handle=handle, source_url=url))
    root = ET.fromstring(svg)
    groups = [node for node in root.findall("s:g", NS) if node.find("s:title", NS) is not None]
    sources = [source for source in (handle, url) if source.strip()]
    expected = (
        [f"DECLARED · {COPY[locale]['source']}: {source}" for source in sources]
        if sources
        else [f"DECLARED · {fallback}"]
    )
    assert [node.find("s:text", NS).text for node in groups] == expected
    assert [node.find("s:title", NS).text for node in groups] == (sources or [fallback])
    assert f"NOT_MEASURED · {COPY[locale]['source']}" not in svg
    assert find_claims(" ".join(root.itertext())) == []
    assert root.findall(".//s:script", NS) == []
    assert not any(key.lower().startswith("on") for node in root.iter() for key in node.attrib)


@pytest.mark.parametrize(
    ("locale", "url"),
    [
        ("es", "rigorscore.com/lectura"),
        ("en", "rigorscore.com/en/reading"),
        ("pt", "rigorscore.com/pt/leitura"),
    ],
)
@pytest.mark.parametrize("claim", [FULL, PublicClaim()])
def test_reader_brand_and_link_fit_inside_the_social_image_height(
    locale: str, url: str, claim: PublicClaim
) -> None:
    root = ET.fromstring(public_card_svg(replace(claim, locale=locale)))
    footers = [node for node in root.findall("s:text", NS) if node.text == url]
    assert len(footers) == 1
    footer = footers[0]
    assert footer.get("text-anchor") == "end"
    assert int(footer.attrib["x"]) == 1160
    assert 570 < int(footer.attrib["y"]) < 630
    assert int(footer.attrib["y"]) + int(footer.attrib["font-size"]) <= 630
    assert find_claims(footer.text) == []


def test_independent_inputs_do_not_hide_other_readings() -> None:
    result = _readings(PublicClaim(trades=45))
    assert result[0][1] is None
    assert result[1][1] == "N=20: 64,2 % · N=100: 68,9 %"
    assert _readings(PublicClaim(trades=5))[1][1] is None
    assert _readings(PublicClaim(trades=20))[1][1] is not None
    assert _readings(PublicClaim(years=0.01, trials=100))[2][1] is None
    assert _readings(PublicClaim(target_r=1, stop_r=1))[3][1] == "50,0 %"
    assert _wilson(0, 45)[0] == 0
    assert _wilson(1, 45)[1] == pytest.approx(1)


def test_untrusted_attribution_is_text_only_and_not_fetched() -> None:
    attack = '<script onload="alert(1)">&</script>'
    svg = public_card_svg(PublicClaim(source_handle=attack, source_url=attack))
    root = ET.fromstring(svg)
    assert "<script" not in svg
    assert attack in " ".join(root.itertext())
    assert not any(key.lower().startswith("on") for node in root.iter() for key in node.attrib)
    assert root.findall(".//s:a", NS) == []
    assert root.findall(".//s:image", NS) == []
    long_source = "https://example.org/" + "x" * 1000
    root = ET.fromstring(public_card_svg(PublicClaim(source_url=long_source)))
    assert long_source in " ".join(root.itertext())  # Full source in tooltip.
    assert all(len(node.text or "") < 160 for node in root.findall(".//s:text", NS))


def test_source_shortening_cannot_introduce_a_guard_hit() -> None:
    source = "x" * 90 + " rentableX tail"
    claim = PublicClaim(source_handle=source)
    assert find_claims(source) == []
    with pytest.raises(ValueError):
        public_card_svg(claim)


def test_wide_attribution_fits_inside_the_card() -> None:
    source = "W" * 100
    root = ET.fromstring(public_card_svg(PublicClaim(source_handle=source, source_url=source)))
    lines = [node for node in root.findall(".//s:text", NS) if source in (node.text or "")]
    assert len(lines) == 2
    for node in lines:
        assert len(node.text) * int(node.attrib["font-size"]) <= 1120


@pytest.mark.parametrize(
    "kwargs",
    [
        {"trades": 0},
        {"trades": 4.5},
        {"trials": True},
        {"trials": 10_000_001},
        {"win_rate": 71},
        {"win_rate": -0.1},
        {"win_rate": float("nan")},
        {"sharpe": float("inf")},
        {"years": 0},
        {"target_r": -1},
        {"stop_r": 0},
        {"profit_factor": -1},
        {"profit_factor": 10**400},
        {"sharpe": "1.9"},
        {"locale": "fr"},
        {"locale": []},
        {"source_handle": None},
        {"source_handle": "\x00"},
        {"source_url": "\ud800"},
        {"source_handle": "rentable"},
        {"source_handle": "approved"},
        {"source_handle": "lucrativo"},
    ],
)
def test_invalid_values_and_unsafe_claims_are_refused(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        PublicClaim(**kwargs)
