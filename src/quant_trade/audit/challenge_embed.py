"""Iframe render and installation page for the existing challenge calculator.

The URL maps stay importable by SEO without importing the page shell. The
widget reuses the calculator's form, parser, computation and result rendering.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from html import escape

from quant_trade.audit import challenge_calc as calc

PATHS: dict[str, str] = {
    "es": "/insertar/calculadora-reto",
    "en": "/embed/challenge-calculator",
    "pt": "/pt/incorporar/calculadora-desafio",
}
HELP_PATHS: dict[str, str] = {
    "es": "/herramientas/insertar-calculadora-reto",
    "en": "/tools/embed-challenge-calculator",
    "pt": "/pt/ferramentas/incorporar-calculadora-desafio",
}
PUBLISHED = "2026-10-11"
IFRAME_HEIGHT = 1000


def widget_url(locale: str, firm: str = "") -> str:
    """The widget's own GET destination, with an optional published firm."""
    path = PATHS[calc._locale(locale)]
    if firm and firm not in calc.FIRMS:
        raise KeyError(firm)
    return f"{path}/{firm}" if firm else path


PAGES: dict[str, tuple[str, str]] = {
    widget_url(locale, firm): (locale, firm) for locale in PATHS for firm in ("", *calc.FIRMS)
}

COPY: dict[str, dict[str, str]] = {
    "es": {
        "title": "Inserta la calculadora de reto en tu web",
        "link": "Insertar esta calculadora en tu web",
        "summary": (
            "Calculadora de reto para insertar en tu web: elige firma e idioma y copia el iframe "
            "con reglas publicadas, fuente y fecha."
        ),
        "intro": (
            "Tus lectores pueden explorar objetivos y límites de un reto con sus propias cifras, "
            "sin salir de tu página. La calculadora usa trayectorias sintéticas y las reglas "
            "publicadas por cada firma, con fuente y fecha. El resultado depende de las cifras "
            "declaradas y de los supuestos del modelo; no es una previsión. Elige firma e idioma "
            "y pega el código en el HTML de tu página, manteniendo el enlace «Hecho con Rigor»."
        ),
        "firm": "Firma",
        "all": "Todas las firmas",
        "language": "Idioma de la calculadora",
        "update": "Actualizar vista previa y código",
        "preview": "Vista previa",
        "code": "Código para copiar",
        "credit": "Hecho con Rigor",
        "credit_note": "reglas publicadas por la firma, con fuente y fecha",
        "height": "Puedes ajustar la altura del iframe; el contenido se desplaza dentro de él.",
    },
    "en": {
        "title": "Embed the challenge calculator on your site",
        "link": "Embed this calculator on your site",
        "summary": (
            "Embed the challenge calculator on your site. Choose a firm and language, then copy "
            "the iframe with published rules, sources and dates."
        ),
        "intro": (
            "Readers can explore a challenge's targets and limits with their own figures without "
            "leaving your page. The calculator uses synthetic paths and each firm's published "
            "rules, with a source and date. Results depend on declared figures and model "
            "assumptions; they are not a forecast. Choose a firm and language, then paste the "
            "code into your page's HTML, keeping the “Made with Rigor” link."
        ),
        "firm": "Firm",
        "all": "All firms",
        "language": "Calculator language",
        "update": "Update preview and code",
        "preview": "Preview",
        "code": "Code to copy",
        "credit": "Made with Rigor",
        "credit_note": "rules published by the firm, with a source and date",
        "height": "You can adjust the iframe height; its content scrolls inside it.",
    },
    "pt": {
        "title": "Incorpore a calculadora de desafio no seu site",
        "link": "Incorporar esta calculadora no seu site",
        "summary": (
            "Calculadora de desafio para incorporar no seu site: escolha firma e idioma e copie "
            "o iframe com regras publicadas, fonte e data."
        ),
        "intro": (
            "Seus leitores podem explorar metas e limites de um desafio com seus próprios "
            "números, sem sair da página. A calculadora usa trajetórias sintéticas e as regras "
            "publicadas por cada firma, com fonte e data. O resultado depende dos números "
            "declarados e das hipóteses do modelo; não é uma previsão. Escolha firma e idioma "
            "e cole o código no HTML da sua página, mantendo o link «Feito com Rigor»."
        ),
        "firm": "Firma",
        "all": "Todas as firmas",
        "language": "Idioma da calculadora",
        "update": "Atualizar prévia e código",
        "preview": "Prévia",
        "code": "Código para copiar",
        "credit": "Feito com Rigor",
        "credit_note": "regras publicadas pela firma, com fonte e data",
        "height": "Você pode ajustar a altura do iframe; o conteúdo rola dentro dele.",
    },
}

# Self-contained CSS: no site navigation, scripts, fonts or other requests.
# Tables scroll inside their own container; inputs can shrink at 320 px.
WIDGET_CSS = """
*{box-sizing:border-box}html{color-scheme:light}body{margin:0;background:#f7f7f3;
color:#172c2a;font:15px/1.5 system-ui,sans-serif}main{max-width:760px;margin:auto;
padding:20px 16px 110px}h1{font-size:24px;line-height:1.2;margin:0 0 12px}
h2{font-size:19px;margin:0 0 12px}h3{font-size:16px}p{margin:10px 0}
section,details{background:#fff;border:1px solid #d3dfdb;border-radius:12px;
padding:16px;margin:16px 0}summary{font-weight:650;cursor:pointer}
.form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
.field{min-width:0}label{display:block;font-weight:600;margin-bottom:6px}
input,select,button{font:inherit}input,select{width:100%;min-width:0;padding:10px;
color:inherit;border:1px solid #869b94;border-radius:6px;background:#fff}
button{padding:11px 18px;margin-top:16px;border:0;border-radius:6px;
background:#173f37;color:#fff;cursor:pointer}.help,.muted{font-size:13px;color:#4d645d}
.help{margin:6px 0 0}.badge{display:inline-block;font-size:10px;font-weight:600;
padding:2px 5px;border-radius:4px;background:#eef1e9;color:#3c5146}
.badge.NOT_MEASURED{background:#fff1d2;color:#684e16}.tscroll{max-width:100%;
overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;vertical-align:top;padding:9px 6px;border-bottom:1px solid #dde5df}
.calc-result th{width:58%}.calc-result td{overflow-wrap:anywhere}
.challenge-phases,.challenge-rules{min-width:540px}a{color:#155d4f}
a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible,
summary:focus-visible{outline:3px solid #ad641c;outline-offset:3px}
.error,.warning,.flash{padding:10px;background:#fff4df;border-radius:6px}
ul{padding-left:20px}.challenge-notes svg{display:none}
.embed-credit{position:fixed;inset:auto 0 0;background:#eef3eb;border-top:1px solid #bacdc3;
padding:12px 16px;text-align:center;font-size:12px;z-index:1}
.embed-credit p{max-width:728px;margin:0 auto}.embed-credit a{font-weight:700}
@media(max-width:519px){.form-grid{grid-template-columns:1fr}main{padding:16px 12px 110px}
section,details{padding:12px}h1{font-size:22px}th,td{padding:8px 4px}}
"""


def _links_in_new_tab(fragment: str) -> str:
    """Keep auxiliary links from navigating the iframe to a page that rejects framing.

    This handles only the trusted, escaped markup from the shared calculator
    renderers. Forms retain their own GET destination inside the widget.
    """

    def opening_tag(match: re.Match[str]) -> str:
        tag = match.group(0)
        existing = re.search(r"\srel=(['\"])(.*?)\1", tag)
        rel = list(dict.fromkeys([*(existing.group(2).split() if existing else []), "noopener"]))
        tag = re.sub(r"\s(?:target|rel)=(['\"])(.*?)\1", "", tag)
        return tag[:-1] + f" target='_blank' rel='{escape(' '.join(rel))}'>"

    return re.sub(r"<a\b[^>]*>", opening_tag, fragment)


def widget_page(
    *,
    locale: str = "es",
    firm: str = "",
    base_url: str = "",
    values: Mapping[str, str] | None = None,
    duplicate: bool = False,
    limited: bool = False,
) -> str:
    """The same calculator and results in a compact, session-free document."""
    from quant_trade.audit.challenge_pages import _rules, calculator_sections

    locale = calc._locale(locale)
    words, credit = calc.COPY[locale], COPY[locale]
    sections, value = calculator_sections(
        locale=locale,
        firm=firm,
        values=values,
        duplicate=duplicate,
        limited=limited,
        action=widget_url(locale, firm),
    )
    title = calc.firm_copy(firm, locale)["title"] if firm else words["nav"]
    canonical = base_url.rstrip("/") + calc.challenge_url(locale, firm)
    body = "".join(
        f"<section><h2>{escape(title_)}</h2>{html}</section>" for title_, html in sections
    )
    programs = calc.firm_programs(firm) if firm else (value.program if value else calc.PROGRAMS[0],)
    body += (
        f"<details><summary>{escape(words['rules_title'])}</summary>"
        f"{_rules(programs, locale, firm=firm)}</details>"
        f"<details><summary>{escape(words['how_title'])}</summary><ul>"
        + "".join(f"<li>{escape(item)}</li>" for item in words["how"])
        + "</ul></details>"
    )
    body = _links_in_new_tab(body)
    return (
        f"<!doctype html><html lang='{locale}'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{escape(title)} · Rigor</title><meta name='robots' content='noindex'>"
        f"<link rel='canonical' href='{escape(canonical)}'><style>{WIDGET_CSS}</style></head>"
        f"<body><main><h1>{escape(title)}</h1><p class='help'>{escape(words['lead'])}</p>"
        f"{body}</main><footer class='embed-credit'><p>"
        f"<a href='{escape(canonical)}?ref=embed' target='_blank' rel='noopener'>"
        f"{escape(credit['credit'])}</a> · {escape(credit['credit_note'])}</p>"
        "</footer></body></html>"
    )


def instructions_page(
    *,
    locale: str = "es",
    firm: str = "",
    widget_locale: str | None = None,
    base_url: str = "",
) -> str:
    """GET selectors, a preview and copyable iframe code for publishers."""
    from quant_trade.audit.pages import _language_crumbs, _page, _page_hero
    from quant_trade.audit.seo import PageMeta, head_meta
    from quant_trade.audit.tools_hub import COPY as TOOLS_COPY
    from quant_trade.audit.tools_hub import tools_url

    locale = calc._locale(locale)
    widget_locale = calc._locale(widget_locale or locale)
    words = COPY[locale]
    iframe_title = calc.COPY[widget_locale]["nav"]
    if firm:
        iframe_title += f" · {calc.FIRMS[firm]}"
    src = base_url.rstrip("/") + widget_url(widget_locale, firm)
    code = (
        f"<iframe src='{escape(src)}' width='100%' height='{IFRAME_HEIGHT}' "
        f"loading='lazy' title='{escape(iframe_title)}'></iframe>"
    )

    def select(name: str, options: Mapping[str, str], chosen: str, label: str) -> str:
        items = "".join(
            f"<option value='{escape(key)}'{' selected' if key == chosen else ''}>"
            f"{escape(text)}</option>"
            for key, text in options.items()
        )
        return (
            f"<div class='field'><label for='embed-{name}'>{escape(label)}</label>"
            f"<select id='embed-{name}' name='{name}'>{items}</select></div>"
        )

    form = (
        f"<form method='get' action='{HELP_PATHS[locale]}'><div class='form-grid'>"
        + select("firm", {"": words["all"], **calc.FIRMS}, firm, words["firm"])
        + select(
            "locale",
            {"es": "Español", "en": "English", "pt": "Português"},
            widget_locale,
            words["language"],
        )
        + f"</div><button class='btn btn-dark' type='submit'>{escape(words['update'])}</button>"
        "</form>"
    )
    title = f"{words['title']} · Rigor"
    meta = head_meta(
        PageMeta(title=title, description=words["summary"], locale=locale, paths=HELP_PATHS),
        base_url=base_url,
    )
    crumbs = (
        f"<a href='{tools_url(locale)}'>{escape(TOOLS_COPY[locale]['nav'])}</a>"
        + _language_crumbs(HELP_PATHS, locale)
    )
    body = (
        _page_hero(TOOLS_COPY[locale]["eyebrow"], words["title"], words["intro"], crumbs)
        + "<div class='paper page-main'><div class='wrap wrap-mid'>"
        + form
        + f"<section><h2>{escape(words['code'])}</h2>"
        f"<label for='embed-code'>{escape(words['code'])}</label>"
        f"<textarea id='embed-code' readonly rows='5' spellcheck='false' "
        f"style='width:100%;font-family:monospace'>{escape(code)}</textarea>"
        f"<p class='help'>{escape(words['height'])}</p></section>"
        f"<section><h2>{escape(words['preview'])}</h2>{code}</section></div></div>"
    )
    return _page(title, locale, body, meta_html=meta, alternates=HELP_PATHS, solid_nav=True)
