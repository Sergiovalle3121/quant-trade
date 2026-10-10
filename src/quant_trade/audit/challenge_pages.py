"""The challenge calculator's pages: the main one and one per firm with a preset.

Rendering only. The figures come from ``challenge_calc`` (the report's
simulator on synthetic days built from declared figures) and the page shell
from ``pages``; nothing here computes a probability of its own.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlencode

from quant_trade.audit import challenge_calc as calc
from quant_trade.audit import firmfit, reading, winrate
from quant_trade.audit.articles import ARTICLES_BY_KEY, _num, article_url
from quant_trade.audit.audiences import AUDIENCE_PAGES, audience_url
from quant_trade.audit.guides import GUIDES_COPY
from quant_trade.audit.i18n import localize
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
from quant_trade.audit.prop_presets import PRESETS, ChallengeRules
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

#: The article and the case page the calculator belongs with.
ARTICLE_KEY = "cuantos-intentos-reto-prop-firm"
AUDIENCE_SLUG = "retos-prop-firm"


def _percent(value: float, locale: str) -> str:
    return f"{_num(value * 100, locale, 1)} %"


def _phase_name(rules: ChallengeRules, locale: str) -> str:
    phase = localize(rules.phase, locale)
    word = "phase" if locale == "en" else "fase"
    return f"{word} {phase}" if rules.phase[:1].isdigit() else phase


def _program_name(key: str, locale: str) -> str:
    rules = PRESETS[key]
    return f"{rules.firm} · {localize(rules.program, locale)}"


def _option_label(key: str, locale: str) -> str:
    phases = calc.COPY[locale]["phases"][calc.phase_count(key)]
    return f"{_program_name(key, locale)} ({phases})"


def _declared(text: str, locale: str) -> str:
    return f"<b>{_e(text)}</b> {_badge('DECLARED', locale)}"


def _missing(reason: str, locale: str) -> str:
    return f"{_badge('NOT_MEASURED', locale)} <span class='muted'>{_e(reason)}</span>"


def _figure(figure: Mapping[str, Any] | None, locale: str, reason: str) -> str:
    """A probability computed from the declared figures, or why there is none."""
    if not figure or figure.get("evidence") != "MEASURED":
        return _missing(reason, locale)
    return _declared(_percent(float(figure["value"]), locale), locale)


def _has_daily(key: str) -> bool:
    return any(PRESETS[k].max_daily_loss is not None for k in firmfit.program_keys(key))


def _days(run: calc.ProgramRun, locale: str) -> str:
    """The median business days to the target, phase by phase when there are several."""
    words = calc.COPY[locale]
    parts: list[str] = []
    for index, (_key, result) in enumerate(run.phases, start=1):
        median = (result.get("days_to_target") or {}).get("p50") or {}
        if median.get("evidence") != "MEASURED":
            return _missing(words["no_target"], locale)
        text = words["days_unit"].format(n=_num(float(median["value"]), locale, 0))
        parts.append(
            words["phase_value"].format(n=index, value=text) if len(run.phases) > 1 else text
        )
    return _declared(" · ".join(parts), locale)


def _horizon(run: calc.ProgramRun) -> int:
    method = run.phases[0][1].get("method") or {}
    return int(method.get("horizon_business_days") or 250)


def _outcome_rows(
    key: str, outcome: Mapping[str, Any], locale: str, *, compact: bool = False
) -> list[tuple[str, str, str]]:
    """(row key, label, cell) for the program's outcome: reach, best day and limits.

    ``compact`` (the comparison tables) leaves out the daily limit of a program
    that has none; the result table keeps the row and says so."""
    words = calc.COPY[locale]
    several = calc.phase_count(key) > 1
    target = words["row_target_all" if several else "row_target"]
    rows = [("pass", target, _figure(outcome.get("pass"), locale, words["no_target"]))]
    if outcome.get("pass_within_best_day"):
        rows.append(
            (
                "best_day",
                words["row_best_day"],
                _figure(outcome["pass_within_best_day"], locale, words["no_target"]),
            )
        )
    if _has_daily(key):
        daily = _figure(outcome.get("fail_daily_loss"), locale, words["no_target"])
        rows.append(("daily", words["row_daily"], daily))
    elif not compact:
        rows.append(("daily", words["row_daily"], _missing(words["no_daily"], locale)))
    rows.append(("total", words["row_total"], _figure(outcome.get("fail_total_loss"), locale, "")))
    return rows


def _identical(locale: str) -> str:
    return f"<p class='warning'>{_e(calc.COPY[locale]['identical_days'])}</p>"


def _result(value: calc.ChallengeInput, reading_: calc.ChallengeReading, locale: str) -> str:
    """The declared program: its outcome, the fee figures and each phase."""
    words = calc.COPY[locale]
    run = reading_.declared
    phases = words["phases"][calc.phase_count(value.program)]
    program = words["simulated"].format(program=_program_name(value.program, locale), phases=phases)
    head = f"<p data-challenge-program>{_e(program)}</p>"
    if not run.measured:
        return head + _identical(locale)
    horizon = _horizon(run)
    rows = _outcome_rows(value.program, run.outcome, locale)
    rows.append(
        (
            "unfinished",
            words["row_unfinished"].format(days=horizon),
            _figure(run.outcome.get("unfinished"), locale, ""),
        )
    )
    rows.append(("days", words["row_days"], _days(run, locale)))
    if reading_.attempts is not None:
        attempts = _declared(
            words["attempts_unit"].format(n=_num(reading_.attempts, locale, 1)), locale
        )
    else:
        attempts = _missing(words["no_target"], locale)
    rows.append(("attempts", words["row_attempts"], attempts))
    if value.fee is not None:
        rows.append(
            ("fee", words["row_fee"], _declared(f"USD {_num(value.fee, locale, 0)}", locale))
        )
    if reading_.cost is not None:
        cost = _declared(f"USD {_num(reading_.cost, locale, 0)}", locale)
    elif value.fee is None:
        cost = _missing(words["no_fee"], locale)
    else:
        cost = _missing(words["no_target"], locale)
    rows.append(("cost", words["row_cost"], cost))
    table = "".join(
        f"<tr data-row='{key}'><th scope='row'>{_e(label)}</th><td>{cell}</td></tr>"
        for key, label, cell in rows
    )
    note = words["paths_note"].format(
        samples=_num(calc.SAMPLES, locale, 0), days=_num(calc.SYNTHETIC_DAYS, locale, 0)
    )
    body = (
        head + f"<table class='calc-result' data-challenge-result><tbody>{table}</tbody></table>"
        f"<p class='help'>{_badge('DECLARED', locale)} {_e(words['computed'])}. {_e(note)}</p>"
        f"<p class='help'>{_e(words['fee_note'])}</p>"
    )
    if len(run.phases) > 1:
        body += f"<h3>{_e(words['phase_title'])}</h3>" + _phase_table(run, locale)
    return body


def _phase_table(run: calc.ProgramRun, locale: str) -> str:
    words = calc.COPY[locale]
    rows = ""
    for key, result in run.phases:
        probability = result["probability"]
        median = (result.get("days_to_target") or {}).get("p50") or {}
        days = (
            _declared(_num(float(median["value"]), locale, 0), locale)
            if median.get("evidence") == "MEASURED"
            else _missing(words["no_target"], locale)
        )
        daily = (
            _figure(probability["fail_daily_loss"], locale, "")
            if PRESETS[key].max_daily_loss is not None
            else _missing(words["no_daily"], locale)
        )
        rows += (
            f"<tr><th scope='row'>{_e(_phase_name(PRESETS[key], locale))}</th>"
            f"<td>{_figure(probability['pass'], locale, '')}</td><td>{daily}</td>"
            f"<td>{_figure(probability['fail_total_loss'], locale, '')}</td>"
            f"<td>{_figure(probability['unfinished'], locale, '')}</td><td>{days}</td></tr>"
        )
    head = "".join(
        f"<th scope='col'>{_e(words[name])}</th>"
        for name in ("col_phase", "col_target", "col_daily", "col_total", "col_unfinished")
    )
    return (
        "<div class='tscroll'><table class='challenge-phases'><thead><tr>"
        f"{head}<th scope='col'>{_e(words['col_days'])}</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
    )


def _lower(value: calc.ChallengeInput, reading_: calc.ChallengeReading, locale: str) -> str:
    """The Rigor angle: the same program at the lower end of the win rate's interval."""
    words = calc.COPY[locale]
    if value.trades is None or reading_.interval is None or reading_.lower is None:
        link = winrate.WINRATE_PATH[locale]
        return (
            f"<p data-challenge-lower-missing>{_badge('NOT_MEASURED', locale)} "
            f"{_e(words['lower_missing'])}</p>"
            f"<p><a href='{_e(link)}'>{_e(words['lower_link'])}</a></p>"
        )
    low = reading_.interval[0]
    rate = _percent(value.win_rate, locale)
    lower_rate = _percent(low, locale)
    text = words["lower_text"].format(n=_num(value.trades, locale, 0), rate=rate, low=lower_rate)
    link = (
        winrate.WINRATE_PATH[locale]
        + "?"
        + urlencode({"trades": str(value.trades), "win_rate": calc.share_values(value)["win_rate"]})
    )
    body = f"<p data-challenge-lower>{_e(text)}</p>"
    declared, lower = reading_.declared, reading_.lower
    if not declared.measured or not lower.measured:
        body += _identical(locale)
    else:
        mine = {
            key: cell
            for key, _label, cell in _outcome_rows(
                value.program, declared.outcome, locale, compact=True
            )
        }
        theirs = _outcome_rows(value.program, lower.outcome, locale, compact=True)
        rows = "".join(
            f"<tr><th scope='row'>{_e(label)}</th><td>{mine.get(key, '')}</td><td>{cell}</td></tr>"
            for key, label, cell in theirs
        )
        body += (
            "<div class='tscroll'><table class='challenge-lower'><thead><tr>"
            f"<th scope='col'>{_e(words['win_rate'])}</th>"
            f"<th scope='col'>{_e(rate)}</th><th scope='col'>{_e(lower_rate)}</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div>"
        )
    return (
        body + f"<p><a href='{_e(link)}' data-challenge-winrate>{_e(words['lower_link'])}</a></p>"
    )


def _sizes(value: calc.ChallengeInput, reading_: calc.ChallengeReading, locale: str) -> str:
    words = calc.COPY[locale]
    rows = ""
    for size, outcome in reading_.sizes:
        cells = "".join(
            f"<td>{cell}</td>"
            for _key, _label, cell in _outcome_rows(value.program, outcome, locale, compact=True)
        )
        label = _num(size, locale, 1).removesuffix(",0").removesuffix(".0") + "x"
        rows += f"<tr><th scope='row'>{_e(label)}</th>{cells}</tr>"
    labels = [
        label
        for _key, label, _cell in _outcome_rows(
            value.program, reading_.declared.outcome, locale, compact=True
        )
    ]
    head = "".join(f"<th scope='col'>{_e(label)}</th>" for label in labels)
    return (
        f"<p>{_e(words['size_text'])}</p><div class='tscroll'><table class='challenge-sizes'>"
        f"<thead><tr><th scope='col'>{_e(words['col_size'])}</th>{head}</tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
    )


def _share(value: calc.ChallengeInput, locale: str, firm: str, base_url: str) -> str:
    words, share = calc.COPY[locale], SHARE_COPY[locale]
    url = base_url.rstrip("/") + calc.share_url(locale, value, firm)
    text = words["share_text"].format(program=_program_name(value.program, locale), url=url)
    intent = "https://x.com/intent/post?" + urlencode({"text": text})
    copy_link = reading.COPY[locale]["copy_link"]
    return (
        f"<div data-public-share><p class='help'>{_e(words['share_public'])}</p>"
        "<textarea id='challenge-share-link' readonly hidden rows='3' style='width:100%' "
        f"aria-label='{_e(copy_link)}'>{_e(url)}</textarea>"
        f"<label for='challenge-share-text'>{_e(share['copy'])}</label>"
        "<textarea id='challenge-share-text' readonly rows='5' style='width:100%'>"
        f"{_e(text)}</textarea><div class='copy-row'>"
        "<button class='btn btn-ghost' type='button' data-copy='challenge-share-link' "
        f"data-done='{_e(share['done'])}' data-fallback='{_e(share['fallback'])}' hidden>"
        f"{_e(copy_link)}</button>"
        "<button class='btn btn-dark' type='button' data-copy='challenge-share-text' "
        f"data-done='{_e(share['done'])}' data-fallback='{_e(share['fallback'])}' hidden>"
        f"{_e(share['copy'])}</button><a class='btn btn-ghost' href='{_e(intent)}' "
        f"rel='noopener noreferrer'>{_e(share['post'])}</a></div>"
        "<p class='muted' data-copy-status role='status' aria-live='polite'></p></div>"
    )


def _daily_rule(rules: ChallengeRules, locale: str) -> str:
    words = calc.COPY[locale]
    if rules.max_daily_loss is None:
        return words["daily_none"]
    basis = "daily_day" if rules.daily_loss_basis == "start_of_day" else "daily_initial"
    return words[basis].format(value=calc._pct(rules.max_daily_loss, locale))


def _total_rule(rules: ChallengeRules, locale: str) -> str:
    words = calc.COPY[locale]
    kind = {"trailing_eod": "total_trailing", "trailing_eod_lock": "total_lock"}.get(
        rules.total_loss_type, "total_static"
    )
    text = words[kind].format(value=calc._pct(rules.max_total_loss, locale))
    account = calc.account_size(rules.key)
    if account is not None:
        loss = calc._amount(rules.max_total_loss * account, locale)
        text += f" (USD {loss}, {words['account'].format(amount=calc._amount(account, locale))})"
    return text


def _best_rule(rules: ChallengeRules, locale: str) -> str:
    words = calc.COPY[locale]
    if rules.best_day_limit is None:
        return words["best_none"]
    kind = "best_positive" if rules.best_day_basis == "positive_days" else "best_target"
    return words[kind].format(value=calc._pct(rules.best_day_limit, locale))


def _rules(programs: Sequence[str], locale: str, *, firm: str = "") -> str:
    """The rules table of ``programs``, phase by phase, with sources, dates and notes."""
    words = calc.COPY[locale]
    rows = ""
    sources: dict[str, tuple[str, str]] = {}
    notes: list[str] = []
    for program in programs:
        for key in firmfit.program_keys(program):
            rules = PRESETS[key]
            label = _program_name(program, locale)
            phases = firmfit.program_keys(program)
            if len(phases) > 1 or not rules.phase.isdigit():
                label += f" · {_phase_name(rules, locale)}"
            days = str(rules.min_trading_days) if rules.min_trading_days else "0"
            time = (
                words["time_days"].format(n=rules.time_limit_days)
                if rules.time_limit_days
                else words["time_none"]
            )
            rows += (
                f"<tr><th scope='row'>{_e(label)}</th>"
                f"<td>{_e(calc._pct(rules.profit_target, locale))}</td>"
                f"<td>{_e(_daily_rule(rules, locale))}</td>"
                f"<td>{_e(_total_rule(rules, locale))}</td><td>{_e(days)}</td>"
                f"<td>{_e(time)}</td><td>{_e(_best_rule(rules, locale))}</td></tr>"
            )
            sources.setdefault(rules.source_url, (rules.firm, rules.as_of))
            notes.extend(localize(note, locale) for note in rules.notes)
    head = "".join(
        f"<th scope='col'>{_e(words[name])}</th>"
        for name in (
            "col_rule_program",
            "col_rule_target",
            "col_rule_daily",
            "col_rule_total",
            "col_rule_days",
            "col_rule_time",
            "col_rule_best",
        )
    )
    lines = "".join(
        "<p class='help' data-challenge-source>"
        + words["source"].format(
            link=f"<a href='{_e(url)}' rel='noopener nofollow'>"
            f"{_e(words['source_link'].format(firm=name))}</a>",
            date=_e(as_of),
        )
        + "</p>"
        for url, (name, as_of) in sources.items()
    )
    unique = list(dict.fromkeys(notes))
    title = words["notes_title"].format(
        program=calc.FIRMS[firm] if firm else _program_name(programs[0], locale)
    )
    listed = "".join(f"<li>{icon('minus')}<span>{_e(note)}</span></li>" for note in unique)
    return (
        f"<div class='tscroll'><table class='challenge-rules'><thead><tr>{head}</tr></thead>"
        f"<tbody>{rows}</tbody></table></div>{lines}"
        f"<p class='flash' data-challenge-affiliation>{_e(words['not_affiliated'])}</p>"
        f"<h3>{_e(title)}</h3><ul class='checks nots'>{listed}</ul>"
    )


def _form(
    locale: str, firm: str, shown: Mapping[str, str], errors: Sequence[str], limited: bool
) -> str:
    words = calc.COPY[locale]
    form = ""
    for code in errors:
        form += f"<p class='error' role='alert'>{_e(words['error_' + code])}</p>"
    if limited:
        form += f"<p class='error' role='alert'>{_e(words['limited'])}</p>"

    def number(name: str, low: str, high: str, step: str) -> str:
        value = _e(shown.get(name, ""))
        return (
            f"<div class='field'><label for='r-{name}'>{_e(words[name])} "
            f"{_badge('DECLARED', locale)}</label>"
            f"<input type='number' id='r-{name}' name='{name}' min='{low}' max='{high}' "
            f"step='{step}' inputmode='decimal' value='{value}' autocomplete='off' "
            f"aria-describedby='r-{name}-help'>"
            f"<p class='help' id='r-{name}-help'>{_e(words[name + '_help'])}</p></div>"
        )

    def select(name: str, options: Sequence[tuple[str, str]], chosen: str) -> str:
        items = "".join(
            f"<option value='{_e(key)}'{' selected' if key == chosen else ''}>{_e(label)}</option>"
            for key, label in options
        )
        return (
            f"<div class='field'><label for='r-{name}'>{_e(words[name])} "
            f"{_badge('DECLARED', locale)}</label>"
            f"<select id='r-{name}' name='{name}' aria-describedby='r-{name}-help'>{items}</select>"
            f"<p class='help' id='r-{name}-help'>{_e(words[name + '_help'])}</p></div>"
        )

    programs = calc.firm_programs(firm)
    units = [(unit, words["unit_options"][unit]) for unit in calc.UNITS]
    form += (
        f"<p>{_e(words['optional'])}</p>"
        f"<form method='get' action='{_e(calc.challenge_url(locale, firm))}' class='calc-form'>"
        "<div class='form-grid'>"
        + select(
            "program",
            [(key, _option_label(key, locale)) for key in programs],
            shown.get("program", programs[0]),
        )
        + number("win_rate", "0", "100", "any")
        + select("unit", units, shown.get("unit", "pct"))
        + number("risk", "0", "20", "any")
        + number("avg_win", "0", "100", "any")
        + number("avg_loss", "0", "100", "any")
        + number("per_day", "0.1", "50", "any")
        + number("trades", "1", "10000000", "1")
        + number("fee", "0", "100000", "any")
        + f"</div><button class='btn btn-dark' type='submit'>{_e(words['submit'])}</button></form>"
    )
    return form


def _further(locale: str, firm: str) -> str:
    words = calc.COPY[locale]
    title = ARTICLES_BY_KEY[ARTICLE_KEY].text[locale].title
    audience = next(page for page in AUDIENCE_PAGES if page.slug == AUDIENCE_SLUG)
    links: list[tuple[str, str]] = []
    if firm:
        links.append((words["main_link"], calc.challenge_url(locale)))
    links += [
        (words["firm_link"].format(firm=name), calc.challenge_url(locale, slug))
        for slug, name in calc.FIRMS.items()
        if slug != firm
    ]
    links += [
        (str(winrate.COPY[locale]["nav"]), winrate.WINRATE_PATH[locale]),
        (title, article_url(ARTICLE_KEY, locale)),
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


def challenge_page(
    *,
    locale: str = "es",
    firm: str = "",
    base_url: str = "",
    values: Mapping[str, str] | None = None,
    duplicate: bool = False,
    limited: bool = False,
) -> str:
    """The calculator, or a firm's page of it: form, result, rules and sources.

    ``values`` are the query's fields as they arrived. ``duplicate`` says a
    field came twice (refused like the win-rate calculator does) and
    ``limited`` that this address is past ``REQUESTS_PER_HOUR``: then the
    page shows the form and the message, and nothing is computed."""
    locale = calc._locale(locale)
    if firm and firm not in calc.FIRMS:
        raise KeyError(firm)
    words = calc.COPY[locale]
    raw = dict(values or {})
    parsed = calc.parse(raw, firm) if calc.submitted(raw) and not duplicate else None
    errors: tuple[str, ...] = ("invalid",) if duplicate else ()
    shown: Mapping[str, str] = {}
    value = None
    if parsed is not None:
        errors, shown, value = parsed.errors, parsed.shown, parsed.value
    sections: list[tuple[str, str]] = [
        (words["form_title"], _form(locale, firm, shown, errors, limited))
    ]
    if value is not None and not limited:
        figures = calc.compute(value)
        sections.append((words["result_title"], _result(value, figures, locale)))
        sections.append((words["lower_title"], _lower(value, figures, locale)))
        if figures.sizes:
            sections.append((words["size_title"], _sizes(value, figures, locale)))
        sections.append((words["share_title"], _share(value, locale, firm, base_url)))
    programs = calc.firm_programs(firm) if firm else (value.program if value else calc.PROGRAMS[0],)
    rules_title = (
        words["firm_rules_title"].format(firm=calc.FIRMS[firm]) if firm else words["rules_title"]
    )
    sections.append((rules_title, _rules(programs, locale, firm=firm)))
    faq: tuple[tuple[str, str], ...] = ()
    if firm:
        faq = calc.firm_faq(firm, locale)
        sections.append(
            (
                words["faq_title"],
                "".join(f"<h3>{_e(q)}</h3><p>{_e(a)}</p>" for q, a in faq),
            )
        )
    how = "".join(f"<li>{icon('check')}<span>{_e(item)}</span></li>" for item in words["how"])
    cta = (
        f"<p>{_e(words['cta'])}</p><p><a class='btn btn-dark' href='{_e(audit_path(locale))}'>"
        f"{_e(words['cta_button'])}<span class='go'>{icon('arrow')}</span></a> "
        f"<a href='{_e(_sample_url(locale))}'>{_e(words['sample_link'])}</a></p>"
    )
    sections += [
        (words["how_title"], f"<ul class='checks'>{how}</ul>"),
        (words["cta_title"], cta),
        (words["read_title"], _further(locale, firm)),
    ]
    if firm:
        own = calc.firm_copy(firm, locale)
        title_text, seo_title, summary, lead = (
            own["title"],
            own["seo_title"],
            own["summary"],
            own["lead"],
        )
    else:
        title_text, seo_title, summary, lead = (
            words["title"],
            words["seo_title"],
            words["summary"],
            words["lead"],
        )
    title = f"{seo_title} · {BRAND}"
    paths = calc.page_paths(firm)
    meta = head_meta(
        PageMeta(title=title, description=summary, locale=locale, paths=paths, image_alt=title),
        base_url=base_url,
    ) + web_application_structured_data(
        title_text if firm else words["nav"],
        summary,
        base_url.rstrip("/") + calc.challenge_url(locale, firm),
        locale,
    )
    if faq:
        meta += faq_structured_data(faq)
    crumbs = f"<a href='{_e(_home(locale))}'>{_e(GUIDES_COPY[locale]['back'])}</a>" + (
        _language_crumbs(paths, locale)
    )
    body = (
        _page_hero(words["eyebrow"], title_text, lead, crumbs)
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


__all__ = ["ARTICLE_KEY", "AUDIENCE_SLUG", "challenge_page"]
