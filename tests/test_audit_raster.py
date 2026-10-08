"""PNG conversion stays optional and never writes a generated image to disk."""

from __future__ import annotations

import builtins
import struct
import sys
from types import SimpleNamespace

import pytest

from quant_trade.audit import owner_card, raster

SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630"/>'


def test_png_conversion_uses_only_in_memory_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = b"\x89PNG\r\n\x1a\nrendered-card"
    received: list[dict[str, bytes]] = []

    def svg2png(**kwargs: bytes) -> bytes:
        received.append(kwargs)
        return expected

    monkeypatch.setitem(sys.modules, "cairosvg", SimpleNamespace(svg2png=svg2png))
    assert raster.card_png(SVG) is expected
    assert received == [{"bytestring": SVG.encode("utf-8")}]


@pytest.mark.parametrize("error", [ImportError, OSError, RuntimeError, ValueError])
def test_import_failure_is_optional(
    monkeypatch: pytest.MonkeyPatch, error: type[Exception]
) -> None:
    original_import = builtins.__import__

    def unavailable(name: str, *args: object, **kwargs: object) -> object:
        if name == "cairosvg":
            raise error("renderer unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", unavailable)
    assert raster.card_png(SVG) is None
    assert not owner_card.png_available()
    assert owner_card.svg_to_png(SVG) is None


@pytest.mark.parametrize("error", [OSError, RuntimeError, ValueError, TypeError, ZeroDivisionError])
def test_conversion_failure_is_optional(
    monkeypatch: pytest.MonkeyPatch, error: type[Exception]
) -> None:
    def svg2png(**kwargs: bytes) -> bytes:
        raise error("conversion failed")

    monkeypatch.setitem(sys.modules, "cairosvg", SimpleNamespace(svg2png=svg2png))
    assert raster.card_png(SVG) is None
    assert not owner_card.png_available()
    assert owner_card.svg_to_png(SVG) is None


def test_owner_helpers_use_shared_renderer(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[str] = []
    expected = b"\x89PNG\r\n\x1a\nrendered-card"

    def render(svg: str) -> bytes:
        received.append(svg)
        return expected

    monkeypatch.setattr(raster, "card_png", render)
    assert owner_card.png_available()
    assert owner_card.svg_to_png(SVG) is expected
    assert len(received) == 2
    assert 'width="1" height="1"' in received[0]
    assert received[1] == SVG


def test_real_renderer_preserves_png_dimensions() -> None:
    try:
        pytest.importorskip("cairosvg")
    except (OSError, RuntimeError, ValueError) as exc:
        pytest.skip(f"Cairo native library unavailable: {exc}")
    png = raster.card_png(SVG)
    assert png is not None
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert png[12:16] == b"IHDR"
    assert struct.unpack(">II", png[16:24]) == (1200, 630)
