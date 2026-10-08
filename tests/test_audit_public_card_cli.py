"""Offline CLI checks for public cards, safe errors, and optional rasterization."""

from __future__ import annotations

import builtins
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from quant_trade.audit.guard import assert_report_clean
from quant_trade.cli import app

runner = CliRunner()


def _claim(tmp_path: Path, payload: object | None = None) -> Path:
    path = tmp_path / "claim.json"
    path.write_text(json.dumps({} if payload is None else payload), encoding="utf-8")
    return path


def _invoke(claim: Path, out: Path, *options: str):
    result = runner.invoke(
        app, ["audit", "public-card", "--json", str(claim), "--out", str(out), *options]
    )
    assert_report_clean(result.output)
    return result


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_public_card_writes_utf8_svg(tmp_path: Path, locale: str) -> None:
    claim = _claim(
        tmp_path,
        {
            "source_handle": "@fuente_pública",
            "source_url": "https://example.com/public-post",
            "trades": 300,
            "win_rate": 0.6,
            "profit_factor": 1.5,
            "sharpe": 1.1,
            "years": 2.0,
            "trials": 1,
            "target_r": 1.0,
            "stop_r": 1.0,
            "locale": locale,
        },
    )
    out = tmp_path / "nested" / "card.svg"
    result = _invoke(claim, out)
    assert result.exit_code == 0, result.output
    svg = out.read_text(encoding="utf-8")
    assert "<svg" in svg
    assert "@fuente_pública" in svg
    assert "DECLARED" in svg
    assert_report_clean(svg)
    assert not out.with_suffix(".png").exists()


def test_public_card_accepts_missing_figures(tmp_path: Path) -> None:
    result = _invoke(_claim(tmp_path), tmp_path / "card.svg")
    assert result.exit_code == 0, result.output
    assert "NOT_MEASURED" in (tmp_path / "card.svg").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "text",
    [
        "not JSON",
        "[]",
        '"string"',
        "null",
        '{"guaranteed profit": 1}',
        '{"win_rate": 0.6, "win_rate": 0.7}',
        '{"sharpe": NaN}',
        '{"sharpe": Infinity}',
        '{"sharpe": -Infinity}',
        '{"sharpe": 1e999}',
        '{"win_rate": 70}',
        '{"win_rate": true}',
        '{"trades": 3.5}',
        '{"trades": -3}',
        '{"trials": 0}',
        '{"years": 0}',
        '{"profit_factor": -1}',
        '{"target_r": 0}',
        '{"stop_r": 0}',
        '{"locale": "guaranteed profit"}',
        '{"source_handle": []}',
    ],
)
def test_public_card_rejects_invalid_json_and_values_without_echoing(
    tmp_path: Path, text: str
) -> None:
    claim = tmp_path / "claim.json"
    claim.write_text(text, encoding="utf-8")
    out = tmp_path / "card.svg"
    result = _invoke(claim, out)
    assert result.exit_code == 2
    assert "guaranteed profit" not in result.output
    assert not out.exists()


def test_public_card_rejects_non_utf8(tmp_path: Path) -> None:
    claim = tmp_path / "claim.json"
    claim.write_bytes(b"\xff\xfe")
    result = _invoke(claim, tmp_path / "card.svg")
    assert result.exit_code == 2
    assert "valid UTF-8" in result.output


def test_public_card_missing_input_error_does_not_echo_path(tmp_path: Path) -> None:
    result = _invoke(tmp_path / "guaranteed profit.json", tmp_path / "card.svg")
    assert result.exit_code == 2
    assert "guaranteed profit" not in result.output


def test_public_card_requires_svg_extension(tmp_path: Path) -> None:
    result = _invoke(_claim(tmp_path), tmp_path / "card.json")
    assert result.exit_code == 2
    assert not (tmp_path / "card.json").exists()


@pytest.mark.parametrize("png", [False, True])
def test_public_card_rejects_input_output_collision(tmp_path: Path, png: bool) -> None:
    claim = tmp_path / ("card.png" if png else "card.svg")
    claim.write_text("{}", encoding="utf-8")
    result = _invoke(claim, tmp_path / "card.svg", *(["--png"] if png else []))
    assert result.exit_code == 2
    assert claim.read_text(encoding="utf-8") == "{}"


def test_public_card_rejects_input_output_hardlink(tmp_path: Path) -> None:
    claim = _claim(tmp_path)
    out = tmp_path / "card.svg"
    try:
        out.hardlink_to(claim)
    except OSError:
        pytest.skip("filesystem does not support hardlinks")
    result = _invoke(claim, out)
    assert result.exit_code == 2
    assert claim.read_text(encoding="utf-8") == "{}"


def test_public_card_reads_only_requested_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claim = _claim(tmp_path)
    original = Path.read_text
    reads: list[Path] = []

    def read_text(path: Path, *args: object, **kwargs: object) -> str:
        assert path == claim
        reads.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    result = _invoke(claim, tmp_path / "card.svg")
    assert result.exit_code == 0, result.output
    assert reads == [claim]


@pytest.mark.parametrize("native_missing", [False, True])
def test_public_card_keeps_svg_without_rasterizer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, native_missing: bool
) -> None:
    if native_missing:
        original = builtins.__import__

        def no_cairo(name: str, *args: object, **kwargs: object):
            if name == "cairosvg":
                raise OSError("guaranteed profit: untrusted native error")
            return original(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", no_cairo)
    else:
        monkeypatch.setitem(sys.modules, "cairosvg", None)
    out = tmp_path / "card.svg"
    result = _invoke(_claim(tmp_path), out, "--png")
    assert result.exit_code == 0, result.output
    assert out.exists()
    assert not out.with_suffix(".png").exists()
    assert "Inkscape" in result.output
    assert "guaranteed profit" not in result.output


def test_public_card_writes_optional_png_with_mocked_rasterizer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rendered: list[bytes] = []
    png_bytes = b"\x89PNG\r\n\x1a\nmocked-raster"

    def svg2png(*, bytestring: bytes) -> bytes:
        rendered.append(bytestring)
        return png_bytes

    monkeypatch.setitem(sys.modules, "cairosvg", SimpleNamespace(svg2png=svg2png))
    out = tmp_path / "nested" / "card.svg"
    result = _invoke(_claim(tmp_path), out, "--png")
    assert result.exit_code == 0, result.output
    assert rendered == [out.read_bytes()]
    assert out.with_suffix(".png").read_bytes() == png_bytes
    assert "PNG written" in result.output


def test_public_card_safe_output_write_error(tmp_path: Path) -> None:
    out = tmp_path / "guaranteed profit.svg"
    out.mkdir()
    result = _invoke(_claim(tmp_path), out)
    assert result.exit_code == 2
    assert "cannot write the output SVG" in result.output
    assert "guaranteed profit" not in result.output


def test_public_card_help_passes_guard() -> None:
    result = runner.invoke(app, ["audit", "public-card", "--help"])
    assert result.exit_code == 0, result.output
    # A colour terminal (the CI runner) wraps the help in ANSI codes; read the plain text.
    plain = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", result.output)
    for option in ("--json", "--out", "--png"):
        assert option in plain
    assert_report_clean(plain)
