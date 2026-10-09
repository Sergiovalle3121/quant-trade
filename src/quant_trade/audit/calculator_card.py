"""The luck calculator's result as a share card, with the reader card's look.

Every figure on the card comes from :func:`calculator.compute`, the same call
the page makes, so the picture a link shows and the page it opens agree. The
inputs are the visitor's own claim and stay DECLARED; the outputs are computed
from them, never measured, and the card says it is not an audit. Nothing here
reads a file, the database or the network: four validated numbers in, markup
out.
"""

from __future__ import annotations

import html
import textwrap

from quant_trade.audit import public_card
from quant_trade.audit.calculator import (
    CALCULATOR_PATH,
    COPY,
    CalculatorInput,
    calculator_copy,
    compute,
)
from quant_trade.audit.guard import find_claims

CARD_SIZE = public_card.CARD_SIZE
#: Wrap widths, in characters, for each wrapped text size on the card.
LABEL_SIZE, LABEL_WIDTH = 17, 48
NOTE_SIZE, NOTE_WIDTH = 12, 76
VERDICT_SIZE, VERDICT_WIDTH = 15, 120

_INK = "#202c36"
_MUTED = "#4c5b67"
_ACCENT = "#245d85"


def calculator_card_svg(value: CalculatorInput, locale: str) -> str:
    """A standalone, accessible 1200x675 SVG of the calculator's result.

    Raises ``ValueError`` when the numbers give no measured result (the page
    shows an error then, and no card) or when any visible text would fail the
    claims guard.
    """
    if locale not in COPY:
        raise ValueError("locale must be es, en or pt")
    result = compute(value)
    if result.get("status") != "MEASURED":
        raise ValueError("the calculator has no result to show for these numbers")
    words = calculator_copy(locale, value.periods_per_year)
    card = public_card.COPY[locale]
    width, height = CARD_SIZE
    shown: list[str] = []
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        'aria-labelledby="calculator-card-title calculator-card-desc" '
        f'xml:lang="{html.escape(locale)}">',
        f'<title id="calculator-card-title">{html.escape(words["card_title"])}</title>',
        f'<desc id="calculator-card-desc">{html.escape(words["declared_note"])}</desc>',
        f'<rect width="{width}" height="{height}" fill="#f7f6f2"/>',
        f'<rect width="8" height="{height}" fill="{_ACCENT}"/>',
    ]
    shown += [words["card_title"], words["declared_note"]]

    def text(
        x: int,
        y: int,
        content: str,
        size: int = 16,
        color: str = _INK,
        anchor: str = "start",
    ) -> None:
        shown.append(content)
        parts.append(
            f'<text x="{x}" y="{y}" font-family="Arial, sans-serif" font-size="{size}" '
            f'fill="{color}" text-anchor="{anchor}">{html.escape(content)}</text>'
        )

    def wrapped(
        x: int, y: int, content: str, size: int, width: int, step: int, color: str = _INK
    ) -> int:
        """Draw ``content`` in lines of at most ``width`` characters; return the next y."""
        for line in textwrap.wrap(content, width=width):
            text(x, y, line, size, color)
            y += step
        return y

    text(40, 53, words["card_title"], 32)

    # (b) The four inputs, each the visitor's declaration.
    periods = int(value.periods_per_year)
    inputs = (
        ("sharpe", words["sharpe"], f"{value.sharpe:g}", 24),
        ("years", words["years"], f"{value.years:g}", 24),
        ("trials", words["trials"], f"{value.trials:,}", 24),
        ("periods_per_year", words["frequency"], words["frequency_options"][periods], 17),
    )
    columns = (40, 300, 510, 770)
    for (name, label, figure, size), x in zip(inputs, columns, strict=True):
        parts.append(f'<g data-field="{name}" data-evidence="DECLARED">')
        text(x, 98, f"{label} · DECLARED", NOTE_SIZE, _MUTED)
        if size == LABEL_SIZE:
            # The frequency is a sentence-like label; it keeps the label width rule.
            for index, line in enumerate(textwrap.wrap(figure, width=LABEL_WIDTH)):
                text(x, 126 + index * 20, line, size)
        else:
            text(x, 128, figure, size)
        parts.append("</g>")

    # (c) What the calculator computes from those declarations.
    computed = f"DECLARED · {card['computed']}"
    count = f"{value.trials:,}"
    if result["counted"]:
        figures = (
            ("luck_sharpe", words["luck"].format(n=count), f"{result['luck_sharpe']['value']:.2f}"),
            ("sharpe_after", words["after"], f"{result['sharpe_after']['value']:.2f}"),
            ("haircut", words["haircut"], f"{result['haircut']['value']:.0%}"),
            ("years_needed", words["years_needed"], f"{result['years_needed']['value']:.1f}"),
        )
        for index, (key, label, figure) in enumerate(figures):
            x, y = 40 + (index % 2) * 570, 160 + (index // 2) * 140
            parts += [
                f'<g data-reading="{key}" data-evidence="DECLARED">',
                f'<rect x="{x}" y="{y}" width="550" height="130" rx="9" '
                'fill="#ffffff" stroke="#d6dde0"/>',
            ]
            text(x + 16, y + 22, computed, NOTE_SIZE, _MUTED)
            wrapped(x + 16, y + 46, label, LABEL_SIZE, LABEL_WIDTH, 21)
            text(x + 16, y + 112, figure, 27, _ACCENT)
            parts.append("</g>")
        verdict = words["beats" if result["beats_luck"] else "loses"].format(n=count)
        parts.append('<g data-reading="verdict" data-evidence="DECLARED">')
        next_y = wrapped(40, 462, verdict, VERDICT_SIZE, VERDICT_WIDTH, 20)
        parts.append("</g>")
    else:
        parts.append('<g data-reading="one_trial" data-evidence="DECLARED">')
        wrapped(40, 182, words["one_trial"], VERDICT_SIZE, VERDICT_WIDTH, 20)
        parts.append("</g>")
        for index, row in enumerate(result["what_if"]):
            y = 200 + index * 88
            line = (
                f"{words['col_trials']} {row['trials']:,} · "
                f"{words['col_luck']} {row['luck_sharpe']['value']:.2f} · "
                f"{words['col_years']} {row['years_needed']['value']:.1f}"
            )
            parts += [
                # A row is a hypothetical count of configurations, not something declared.
                f'<g data-reading="what_if" data-trials="{row["trials"]}">',
                f'<rect x="40" y="{y}" width="1120" height="78" rx="9" '
                'fill="#ffffff" stroke="#d6dde0"/>',
            ]
            text(56, y + 47, line, 22, _ACCENT)
            parts.append("</g>")
        next_y = 474
    # The arithmetic's own assumptions: frequency, no skew, normal tails.
    wrapped(40, max(next_y, 474) + 22, words["assumptions"][0], NOTE_SIZE, NOTE_WIDTH, 16, _MUTED)

    # (d) What the card cannot see, where it comes from, and the way to a measurement.
    parts.append('<g data-reading="limits" data-evidence="NOT_MEASURED">')
    text(40, 613, f"NOT_MEASURED · {card['footer']}", 16)
    parts.append("</g>")
    text(1160, 613, f"rigorscore.com{CALCULATOR_PATH[locale]}", 14, _ACCENT, anchor="end")
    text(40, 644, card["cta"], 19)
    parts.append("</svg>")
    if find_claims(" ".join(shown)):
        raise ValueError("card text contains unsupported wording")
    return "".join(parts)


__all__ = ["CARD_SIZE", "calculator_card_svg"]
