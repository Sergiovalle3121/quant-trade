"""Share-card source copy stays complete even while deployed PNGs use a fallback."""

from __future__ import annotations

import html
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from quant_trade.audit.guard import find_claims
from quant_trade.audit.pages import _UI, BADGE_NOTICE, SAMPLE_BANNER
from quant_trade.audit.seo import LOCALES, OG_KINDS
from quant_trade.audit.verdict import class_text


@pytest.fixture(scope="module")
def generator() -> ModuleType:
    # Building markup needs neither Playwright nor a running browser.
    tool = Path(__file__).resolve().parents[1] / "tools" / "make_og_images.py"
    spec = importlib.util.spec_from_file_location("make_og_images", tool)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generator_has_every_language_and_all_fixed_copy_passes_guard(
    generator: ModuleType,
) -> None:
    cards = generator.cards()
    expected = {
        f"og-{kind}-{locale}.png" if kind else f"og-{locale}.png"
        for kind in OG_KINDS
        for locale in LOCALES
    }
    assert set(cards) == expected
    for name, markup in cards.items():
        assert find_claims(markup) == [], name


def test_portuguese_batch_reuses_current_class_sentences_and_fixed_notices(
    generator: ModuleType,
) -> None:
    kinds = ("sample", *(f"class-{overall}" for overall in "ABCD"))
    cards = generator.cards(locales=("pt",), kinds=kinds)
    assert set(cards) == {f"og-{kind}-pt.png" for kind in kinds}
    for overall in "ABCD":
        markup = cards[f"og-class-{overall}-pt.png"]
        head, _, rest = class_text(overall, "pt").partition(": ")
        assert html.escape(head) in markup
        assert html.escape(rest[:1].upper() + rest[1:]) in markup
        assert html.escape(BADGE_NOTICE["pt"]) in markup
        assert html.escape(_UI["pt"]["v_eyebrow"]) in markup
    sample = cards["og-sample-pt.png"]
    assert html.escape(_UI["pt"]["nav_sample"]) in sample
    assert html.escape(SAMPLE_BANNER["pt"].split(":")[0]) in sample
