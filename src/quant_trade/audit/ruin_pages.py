"""The risk-of-ruin calculator's page.

Rendering only. The figures come from ``ruin_calc`` (fixed-size paths from
declared figures, the engine's streak function and the win-rate reader's
Wilson interval) and the page shell from ``pages``; nothing here computes a
probability of its own.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from urllib.parse import urlencode

from quant_trade.audit import challenge_calc, reading, winrate
from quant_trade.audit import ruin_calc as calc
from quant_trade.audit.articles import ARTICLES_BY_KEY, STREAK_ARTICLE_KEY, article_url
from quant_trade.audit.audiences import AUDIENCE_PAGES, audience_url
from quant_trade.audit.guides import GUIDES_COPY
from quant_trade.audit.pages import (
    _badge,
    _doc,
    _e,
    _home,
    _language_crumbs,
    _page,
    _page_hero,
    _sample_url,
    audit_path,
)
from quant_trade.audit.public_card import _num
from quant_trade.audit.seo import (
    BRAND,
    PageMeta,
    faq_structured_data,
    head_meta,
    web_application_structured_data,
)
from quant_trade.audit.sharing import COPY as SHARE_COPY
from quant_trade.audit.theme import icon
from quant_trade.audit.tools_hub import COPY as TOOLS_COPY
from quant_trade.audit.tools_hub import tools_url

#: The articles and the case page the calculator belongs with.
ARTICLE_KEYS = (STREAK_ARTICLE_KEY, "cuantas-operaciones-porcentaje-aciertos")
AUDIENCE_SLUG = "retos-prop-firm"


def _percent(value: float, locale: str) -> str:
    return f"{_num(value * 100, locale, 1)} %"


def _signed(value: float, text: str) -> str:
    """``text`` (``value`` at two decimals) with its sign, so a positive expectancy
    reads as a gain at a glance. The sign follows the rounded value: one that
    rounds to zero shows none, never «-0,00»."""
    rounded = round(value, 2)
    if rounded == 0:
        return text.lstrip("-")
    return "+" + text if rounded > 0 else text


def _declared(text: str, locale: str) -> str:
    return f"<b>{_e(text)}</b> {_badge('DECLARED', locale)}"


def _missing(reason: str, locale: str) -> str:
    return f"{_badge('NOT_MEASURED', locale)} <span class='muted'>{_e(reason)}</span>"


def _amount(value: calc.RuinInput, amount: float, locale: str) -> str:
    """A declared win or loss as it was written: in R, or in % of the balance."""
    if value.unit == "r":
        return str(calc.COPY[locale]["r_unit"]).format(n=_num(amount, locale, 2))
    return f"{_num(amount, locale, 2)} %"


def _rows(
    value: calc.RuinInput, run: calc.RuinRun, locale: str, *, compact: bool = False
) -> list[tuple[str, str, str]]:
    """(row key, label, cell) for one run. ``compact`` (the comparison table)
    keeps the rows that change with the win rate and are read side by side."""
    words = calc.COPY[locale]
    horizon = _num(value.horizon, locale, 0)
    rows = [
        (
            "expectancy_r",
            words["row_expectancy_r"],
            _declared(
                _signed(
                    run.expectancy_r,
                    words["r_unit"].format(n=_num(run.expectancy_r, locale, 2)),
                ),
                locale,
            ),
        )
    ]
    if not compact:
        rows.append(
            (
                "expectancy_pct",
                words["row_expectancy_pct"],
                _declared(
                    _signed(
                        run.expectancy_share * 100,
                        f"{_num(run.expectancy_share * 100, locale, 2)} %",
                    ),
                    locale,
                ),
            )
        )
    rows.append(
        (
            "ruin",
            words["row_ruin"].format(ruin=_percent(value.ruin, locale), horizon=horizon),
            _declared(_percent(run.ruin, locale), locale),
        )
    )
    if not compact:
        classic = (
            _declared(_percent(run.classic, locale), locale)
            if run.classic is not None
            else _missing(words["no_classic"], locale)
        )
        rows.append(("classic", words["row_classic"], classic))
    rows += [
        (
            "dd_median",
            words["row_dd_median"],
            _declared(_percent(run.drawdown_p50, locale), locale),
        ),
        ("dd_p95", words["row_dd_p95"], _declared(_percent(run.drawdown_p95, locale), locale)),
        (
            "streak",
            words["row_streak"],
            _declared(words["trades_unit"].format(n=_num(run.streak_median, locale, 0)), locale),
        ),
    ]
    if not compact:
        rows.append(
            (
                "streak_rare",
                words["row_streak_rare"],
                _declared(words["trades_unit"].format(n=_num(run.streak_rare, locale, 0)), locale),
            )
        )
    return rows


def _result(value: calc.RuinInput, reading_: calc.RuinReading, locale: str) -> str:
    """The declared figures: expectancy, ruin, the classic formula, drawdown and streak."""
    words = calc.COPY[locale]
    run = reading_.declared
    horizon = _num(value.horizon, locale, 0)
    head = words["simulated"].format(
        rate=_percent(value.win_rate, locale),
        win=_amount(value, value.avg_win, locale),
        loss=_amount(value, value.avg_loss, locale),
        ruin=_percent(value.ruin, locale),
        horizon=horizon,
    )
    table = "".join(
        f"<tr data-row='{key}'><th scope='row'>{_e(label)}</th><td>{cell}</td></tr>"
        for key, label, cell in _rows(value, run, locale)
    )
    thresholds = "".join(
        f"<tr><th scope='row'>{_e(_percent(pct / 100.0, locale))}</th>"
        f"<td>{_declared(_percent(share, locale), locale)}</td></tr>"
        for pct, share in run.shortcuts
    )
    note = words["paths_note"].format(samples=_num(calc.SAMPLES, locale, 0), horizon=horizon)
    body = (
        f"<p data-ruin-figures>{_e(head)}</p>"
        f"<table class='calc-result' data-ruin-result><tbody>{table}</tbody></table>"
        f"<p class='help'>{_badge('DECLARED', locale)} {_e(words['computed'])}. {_e(note)}</p>"
    )
    if value.unit == "pct":
        body += f"<p class='help'>{_e(words['r_is_loss'])}</p>"
    if run.classic is not None:
        body += f"<p class='help' data-ruin-classic>{_e(words['classic_note'])}</p>"
    body += (
        f"<h3>{_e(words['thresholds_title'])}</h3>"
        "<div class='tscroll'><table class='ruin-thresholds' data-ruin-thresholds><thead><tr>"
        f"<th scope='col'>{_e(words['col_threshold'])}</th>"
        f"<th scope='col'>{_e(words['col_touch'].format(horizon=horizon))}</th></tr></thead>"
        f"<tbody>{thresholds}</tbody></table></div>"
    )
    return body


def _lower(value: calc.RuinInput, reading_: calc.RuinReading, locale: str) -> str:
    """The Rigor angle: the same figures at the lower end of the win rate's interval."""
    words = calc.COPY[locale]
    if value.trades is None or reading_.interval is None or reading_.lower is None:
        link = winrate.WINRATE_PATH[locale]
        return (
            f"<p data-ruin-lower-missing>{_badge('NOT_MEASURED', locale)} "
            f"{_e(words['lower_missing'])}</p>"
            f"<p><a href='{_e(link)}'>{_e(words['lower_link'])}</a></p>"
        )
    low = reading_.interval[0]
    declared, lower = reading_.declared, reading_.lower
    rate = _percent(value.win_rate, locale)
    lower_rate = _percent(low, locale)
    # The lower bound is a computed figure too: its first mention carries the label.
    marker = ""
    ruin, ruin_low = _percent(declared.ruin, locale), _percent(lower.ruin, locale)
    # When both figures round to the same, the sentence says it stays, not "0.0 % to 0.0 %".
    sentence = words["lower_text_same" if ruin == ruin_low else "lower_text"]
    text = _e(
        sentence.format(
            n=_num(value.trades, locale, 0), rate=rate, low=marker, ruin=ruin, ruin_low=ruin_low
        )
    )
    labelled = f"<b>{_e(lower_rate)}</b> {_badge('DECLARED', locale)}"
    text = text.replace(marker, labelled, 1).replace(marker, _e(lower_rate))
    link = (
        winrate.WINRATE_PATH[locale]
        + "?"
        + urlencode({"trades": str(value.trades), "win_rate": calc.share_values(value)["win_rate"]})
    )
    mine = {key: cell for key, _label, cell in _rows(value, declared, locale, compact=True)}
    rows = "".join(
        f"<tr><th scope='row'>{_e(label)}</th><td>{mine.get(key, '')}</td><td>{cell}</td></tr>"
        for key, label, cell in _rows(value, lower, locale, compact=True)
    )
    return (
        f"<p data-ruin-lower>{text}</p>"
        f"<p class='help'>{_badge('DECLARED', locale)} {_e(words['lower_computed'])}.</p>"
        "<div class='tscroll'><table class='ruin-lower'><thead><tr>"
        f"<th scope='col'>{_e(words['col_figure'])}</th>"
        f"<th scope='col'>{_e(rate)} {_badge('DECLARED', locale)}</th>"
        f"<th scope='col'>{_e(lower_rate)} {_badge('DECLARED', locale)}</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
        f"<p><a href='{_e(link)}' data-ruin-winrate>{_e(words['lower_link'])}</a></p>"
    )


def _share(value: calc.RuinInput, locale: str, base_url: str) -> str:
    words, share = calc.COPY[locale], SHARE_COPY[locale]
    url = base_url.rstrip("/") + calc.share_url(locale, value)
    text = words["share_text"].format(url=url)
    intent = "https://x.com/intent/post?" + urlencode({"text": text})
    copy_link = reading.COPY[locale]["copy_link"]
    return (
        f"<div data-public-share><p class='help'>{_e(words['share_public'])}</p>"
        "<textarea id='ruin-share-link' readonly hidden rows='3' style='width:100%' "
        f"aria-label='{_e(copy_link)}'>{_e(url)}</textarea>"
        f"<label for='ruin-share-text'>{_e(share['copy'])}</label>"
        "<textarea id='ruin-share-text' readonly rows='5' style='width:100%'>"
        f"{_e(text)}</textarea><div class='copy-row'>"
        "<button class='btn btn-ghost' type='button' data-copy='ruin-share-link' "
        f"data-done='{_e(share['done'])}' data-fallback='{_e(share['fallback'])}' hidden>"
        f"{_e(copy_link)}</button>"
        "<button class='btn btn-dark' type='button' data-copy='ruin-share-text' "
        f"data-done='{_e(share['done'])}' data-fallback='{_e(share['fallback'])}' hidden>"
        f"{_e(share['copy'])}</button><a class='btn btn-ghost' href='{_e(intent)}' "
        f"rel='noopener noreferrer'>{_e(share['post'])}</a></div>"
        "<p class='muted' data-copy-status role='status' aria-live='polite'></p></div>"
    )


def _form(locale: str, shown: Mapping[str, str], errors: Sequence[str], limited: bool) -> str:
    words = calc.COPY[locale]
    form = ""
    for code in errors:
        form += f"<p class='error' role='alert'>{_e(words['error_' + code])}</p>"
    if limited:
        form += f"<p class='error' role='alert'>{_e(words['limited'])}</p>"

    def number(name: str, low: str, high: str, step: str) -> str:
        value = _e(shown.get(name, ""))
        return (
            f"<div class='field'><label for='ru-{name}'>{_e(words[name])} "
            f"{_badge('DECLARED', locale)}</label>"
            f"<input type='number' id='ru-{name}' name='{name}' min='{low}' max='{high}' "
            f"step='{step}' inputmode='decimal' value='{value}' autocomplete='off' "
            f"aria-describedby='ru-{name}-help'>"
            f"<p class='help' id='ru-{name}-help'>{_e(words[name + '_help'])}</p></div>"
        )

    def select(name: str, options: Sequence[tuple[str, str]], chosen: str) -> str:
        items = "".join(
            f"<option value='{_e(key)}'{' selected' if key == chosen else ''}>{_e(label)}</option>"
            for key, label in options
        )
        return (
            f"<div class='field'><label for='ru-{name}'>{_e(words[name])} "
            f"{_badge('DECLARED', locale)}</label>"
            f"<select id='ru-{name}' name='{name}' aria-describedby='ru-{name}-help'>{items}"
            f"</select><p class='help' id='ru-{name}-help'>{_e(words[name + '_help'])}</p></div>"
        )

    units = [(unit, words["unit_options"][unit]) for unit in challenge_calc.UNITS]
    form += (
        f"<p>{_e(words['optional'])}</p>"
        f"<form method='get' action='{_e(calc.ruin_url(locale))}' class='calc-form'>"
        "<div class='form-grid'>"
        + number("win_rate", "0", "100", "any")
        + select("unit", units, shown.get("unit", "pct"))
        + number("risk", "0", "20", "any")
        + number("avg_win", "0", "100", "any")
        + number("avg_loss", "0", "100", "any")
        + number("trades", "1", "10000000", "1")
        + number("ruin", "0", "100", "any")
        + number("horizon", str(calc.HORIZON_RANGE[0]), str(calc.HORIZON_RANGE[1]), "1")
        + f"</div><button class='btn btn-dark' type='submit'>{_e(words['submit'])}</button></form>"
    )
    return form


def _further(locale: str) -> str:
    audience = next(page for page in AUDIENCE_PAGES if page.slug == AUDIENCE_SLUG)
    links: list[tuple[str, str]] = [
        (str(winrate.COPY[locale]["nav"]), winrate.WINRATE_PATH[locale]),
        (str(challenge_calc.COPY[locale]["nav"]), challenge_calc.challenge_url(locale)),
        *(
            (ARTICLES_BY_KEY[key].text[locale].title, article_url(key, locale))
            for key in ARTICLE_KEYS
        ),
        (audience.text[locale].title, audience_url(audience.slug, locale)),
        (str(TOOLS_COPY[locale]["nav"]), tools_url(locale)),
    ]
    return (
        "<ul class='aud-others'>"
        + "".join(
            f"<li><a href='{_e(href)}'><span>{_e(label)}</span>{icon('arrow')}</a></li>"
            for label, href in links
        )
        + "</ul>"
    )


def ruin_page(
    *,
    locale: str = "es",
    base_url: str = "",
    values: Mapping[str, str] | None = None,
    duplicate: bool = False,
    limited: bool = False,
) -> str:
    """The calculator: form, result, the lower end of the win rate, share, questions.

    ``values`` are the query's fields as they arrived. ``duplicate`` says a
    field came twice (refused like the other calculators do) and ``limited``
    that this address is past ``REQUESTS_PER_HOUR``: then the page shows the
    form and the message, and nothing is computed."""
    locale = calc._locale(locale)
    words = calc.COPY[locale]
    raw = dict(values or {})
    parsed = calc.parse(raw) if calc.submitted(raw) and not duplicate else None
    errors: tuple[str, ...] = ("invalid",) if duplicate else ()
    shown: Mapping[str, str] = calc.empty_form()
    value = None
    if parsed is not None:
        errors, shown, value = parsed.errors, parsed.shown, parsed.value
    sections: list[tuple[str, str]] = [(words["form_title"], _form(locale, shown, errors, limited))]
    if value is not None and not limited:
        figures = calc.compute(value)
        sections.append((words["result_title"], _result(value, figures, locale)))
        sections.append((words["lower_title"], _lower(value, figures, locale)))
        sections.append((words["share_title"], _share(value, locale, base_url)))
    faq = calc.faq(locale)
    how = "".join(f"<li>{icon('check')}<span>{_e(item)}</span></li>" for item in words["how"])
    cta = (
        f"<p>{_e(words['cta'])}</p><p><a class='btn btn-dark' href='{_e(audit_path(locale))}'>"
        f"{_e(words['cta_button'])}<span class='go'>{icon('arrow')}</span></a> "
        f"<a href='{_e(_sample_url(locale))}'>{_e(words['sample_link'])}</a></p>"
    )
    sections += [
        (words["faq_title"], "".join(f"<h3>{_e(q)}</h3><p>{_e(a)}</p>" for q, a in faq)),
        (words["how_title"], f"<ul class='checks'>{how}</ul>"),
        (words["cta_title"], cta),
        (words["read_title"], _further(locale)),
    ]
    title = f"{words['seo_title']} · {BRAND}"
    paths = dict(calc.RUIN_PATH)
    meta = (
        head_meta(
            PageMeta(
                title=title,
                description=words["summary"],
                locale=locale,
                paths=paths,
                image_alt=title,
            ),
            base_url=base_url,
        )
        + web_application_structured_data(
            words["nav"], words["summary"], base_url.rstrip("/") + calc.ruin_url(locale), locale
        )
        + faq_structured_data(faq)
    )
    crumbs = f"<a href='{_e(_home(locale))}'>{_e(GUIDES_COPY[locale]['back'])}</a>" + (
        _language_crumbs(paths, locale)
    )
    body = (
        _page_hero(words["eyebrow"], words["title"], words["lead"], crumbs)
        + "<div class='paper page-main'><div class='wrap'>"
        + _doc(
            sections,
            locale,
            aside=f"<a class='btn btn-dark btn-sm toc-cta' href='{_e(audit_path(locale))}'>"
            f"{_e(GUIDES_COPY[locale]['form'])}<span class='go'>{icon('arrow')}</span></a>",
        )
        + "</div></div>"
    )
    return _page(title, locale, body, meta_html=meta, alternates=paths, solid_nav=True)


__all__ = ["ARTICLE_KEYS", "AUDIENCE_SLUG", "ruin_page"]
