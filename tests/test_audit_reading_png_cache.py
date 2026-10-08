"""Reader PNG caching is deterministic, bounded and entirely in memory."""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET

import pytest

from quant_trade.audit import reading_png
from quant_trade.audit.reading import FIELDS

SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="675" '
    'viewBox="0 0 1200 675"><text x="15" y="45">Rigor</text></svg>'
)
VALUES = {name: str(index + 1) for index, name in enumerate(FIELDS)}


def test_cache_reuses_bytes_and_stores_only_hashes(monkeypatch: pytest.MonkeyPatch) -> None:
    images: list[bytes] = []

    def render(svg: str) -> bytes:
        png = bytes(bytearray(b"\x89PNG image"))
        images.append(png)
        return png

    monkeypatch.setattr(reading_png.raster, "card_png", render)
    cache = reading_png.ReadingPNGCache()
    first = cache.get("es", VALUES, SVG)
    assert cache.get("es", VALUES, SVG) is first
    assert first is images[0]
    assert len(images) == len(cache) == 1
    assert all(re.fullmatch(r"[a-f0-9]{64}", key) for key in cache._entries)
    assert all(isinstance(value, bytes) for value in cache._entries.values())


def test_extra_parameters_and_whitespace_do_not_change_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def render(svg: str) -> bytes:
        calls.append(svg)
        return b"\x89PNG"

    monkeypatch.setattr(reading_png.raster, "card_png", render)
    cache = reading_png.ReadingPNGCache()
    first = cache.get("es", VALUES, SVG)
    padded = {name: f" {value} " for name, value in VALUES.items()}
    padded.update(ref="private-referral", ignored="not-a-number", locale="en")
    assert cache.get("es", padded, SVG) is first
    assert len(calls) == len(cache) == 1


def test_missing_and_empty_numeric_values_share_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reading_png.raster, "card_png", lambda svg: b"\x89PNG")
    cache = reading_png.ReadingPNGCache()
    first = cache.get("es", {"trades": "20"}, SVG)
    complete = {name: "" for name in FIELDS}
    complete["trades"] = "20"
    assert cache.get("es", complete, SVG) is first
    assert len(cache) == 1


def test_locale_and_each_numeric_field_change_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reading_png.raster, "card_png", lambda svg: b"\x89PNG")
    cache = reading_png.ReadingPNGCache()
    for locale in ("es", "en", "pt"):
        cache.get(locale, VALUES, SVG)
    assert len(cache) == 3
    for field in FIELDS:
        cache.get("es", {**VALUES, field: "42"}, SVG)
    assert len(cache) == 3 + len(FIELDS)


def test_default_cache_is_bounded_to_256(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reading_png.raster, "card_png", lambda svg: b"\x89PNG")
    cache = reading_png.ReadingPNGCache()
    for trades in range(300):
        cache.get("es", {**VALUES, "trades": str(trades)}, SVG)
    assert len(cache) == 256


def test_cache_hits_refresh_least_recently_used_order(monkeypatch: pytest.MonkeyPatch) -> None:
    images: list[bytes] = []

    def render(svg: str) -> bytes:
        png = f"PNG-{len(images)}".encode()
        images.append(png)
        return png

    monkeypatch.setattr(reading_png.raster, "card_png", render)
    cache = reading_png.ReadingPNGCache(max_entries=2)
    first_values = {**VALUES, "trades": "101"}
    second_values = {**VALUES, "trades": "102"}
    first = cache.get("es", first_values, SVG)
    second = cache.get("es", second_values, SVG)
    assert cache.get("es", first_values, SVG) is first
    cache.get("es", {**VALUES, "trades": "103"}, SVG)
    assert len(images) == 3
    assert cache.get("es", first_values, SVG) is first
    assert cache.get("es", second_values, SVG) is not second
    assert len(images) == 4
    assert len(cache) == 2


@pytest.mark.parametrize("capacity", [0, -1])
def test_cache_rejects_nonpositive_capacity(capacity: int) -> None:
    with pytest.raises(ValueError, match="positive"):
        reading_png.ReadingPNGCache(max_entries=capacity)


def test_failed_render_is_not_cached_and_recovers(monkeypatch: pytest.MonkeyPatch) -> None:
    results = iter([None, b"\x89PNG"])
    monkeypatch.setattr(reading_png.raster, "card_png", lambda svg: next(results))
    cache = reading_png.ReadingPNGCache()
    assert cache.get("es", VALUES, SVG) is None
    assert len(cache) == 0
    assert cache.get("es", VALUES, SVG) == b"\x89PNG"
    assert cache.get("es", VALUES, SVG) == b"\x89PNG"
    assert len(cache) == 1


def test_social_image_preserves_card_proportions_with_side_padding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rendered: list[str] = []

    def render(svg: str) -> bytes:
        rendered.append(svg)
        return b"\x89PNG"

    monkeypatch.setattr(reading_png.raster, "card_png", render)
    reading_png.ReadingPNGCache().get("es", VALUES, SVG)
    wrapper = ET.fromstring(rendered[0])
    assert wrapper.attrib == {"width": "1200", "height": "630", "viewBox": "0 0 1200 630"}
    background, card = wrapper
    assert background.attrib == {"width": "1200", "height": "630", "fill": "#f7f6f2"}
    assert card.attrib["viewBox"] == "0 0 1200 675"
    assert card.attrib["preserveAspectRatio"] == "xMidYMid meet"
    assert card.attrib["x"] == "40" and card.attrib["y"] == "0"
    assert card.attrib["width"] == "1120" and card.attrib["height"] == "630"
    assert 1120 / 1200 == 630 / 675
    assert "Rigor" in "".join(card.itertext())
