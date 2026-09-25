"""Every report says what each class requires and marks its own."""

from __future__ import annotations

from quant_trade.audit.guard import find_claims
from quant_trade.audit.report import CLASS_LADDER, LABELS, _ladder_html, render_html
from quant_trade.audit.sample import sample_result


def test_both_languages_cover_the_four_classes_and_pass_the_guard() -> None:
    for locale in ("es", "en"):
        assert [cls for cls, _ in CLASS_LADDER[locale]] == ["A", "B", "C", "D"]
        html = _ladder_html("B", LABELS[locale])
        assert html.count(LABELS[locale]["ladder_you"]) == 1
        assert "<tr class='you'><td><b>B</b>" in html
        assert find_claims(html) == []


def test_the_ladder_is_shown_before_payment_and_on_the_sample() -> None:
    result = sample_result("es", bootstrap_samples=50)
    locked = render_html(result, watermark=True, free_mode=False, redeem_url="/r")
    assert "id='r-ladder'" in locked and LABELS["es"]["ladder_intro"] in locked
    marked = locked.split("<tr class='you'>")[1][:40]
    assert f"<b>{result.verdict.overall}</b>" in marked
