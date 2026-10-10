"""Search and link-preview metadata for the audit site.

Public pages (landing, sample, guides, terms, privacy) get a title, a
description, a canonical URL, their other-language alternate and Open Graph
tags, and are the only pages listed in ``sitemap.xml``, each with the date
of its last change (``page_lastmod``). Private pages (a
client's report or unpaid preview, errors) are ``noindex``, and
``robots.txt`` keeps crawlers out of ``/audits/``, where report URLs carry
the owner's token. A public verification page previews its class and date
when shared, and is ``noindex`` so an unpublished audit does not linger in
search results.
"""

from __future__ import annotations

import html
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from quant_trade.audit.about import ABOUT_PATH
from quant_trade.audit.articles import (
    ARTICLE_PUBLICATION_DATES,
    ARTICLES,
    ARTICLES_COPY,
    Article,
    article_url,
    articles_index_faq,
    articles_index_url,
)
from quant_trade.audit.audiences import AUDIENCE_PAGES, audience_url
from quant_trade.audit.calculator import CALCULATOR_PATH
from quant_trade.audit.challenge_calc import FIRMS as CHALLENGE_FIRMS
from quant_trade.audit.challenge_calc import page_paths as challenge_paths
from quant_trade.audit.examples import EXAMPLES_PATH
from quant_trade.audit.faq import FAQ_PATH
from quant_trade.audit.guides import GUIDES, guide_url, guides_index_url
from quant_trade.audit.institutional import OFFER_UPDATED, REVIEW_PATHS, SAMPLE_PATHS
from quant_trade.audit.legal import LEGAL_PATHS, LEGAL_UPDATED
from quant_trade.audit.method import METHOD_PATH
from quant_trade.audit.pricing import PRICING_PATH
from quant_trade.audit.reading import READING_PATH
from quant_trade.audit.rules_table import RULES_TABLE_PUBLISHED, rules_table_paths
from quant_trade.audit.tools_hub import TOOLS_PATH
from quant_trade.audit.winrate import WINRATE_PATH

LOCALES: tuple[str, ...] = ("es", "en", "pt")

#: The product name. It shows on every page, report and badge, so it must pass
#: the profit-claim guard and never suggest verification, certification,
#: approval, earnings or passing a challenge.
BRAND = "Rigor"
TAGLINE: dict[str, str] = {
    "es": "Auditoría estadística independiente de backtests e historiales",
    "en": "Independent statistical audit of backtests and track records",
    "pt": "Auditoria estatística independente de backtests e históricos",
}
SITE_NAME: dict[str, str] = {locale: f"{BRAND} · {TAGLINE[locale]}" for locale in TAGLINE}
OG_LOCALE: dict[str, str] = {"es": "es_MX", "en": "en_US", "pt": "pt_BR"}
#: The share picture per language.
OG_IMAGE_LOCALE: dict[str, str] = {"es": "es", "en": "en", "pt": "pt"}

NOINDEX = "noindex, nofollow"

#: The page that checks a report file was not edited (``audit/check.py``).
CHECK_PATH: dict[str, str] = {"es": "/comprobar", "en": "/check", "pt": "/pt/comprovar"}

#: The second public sample report, a made-up signal for whoever is about to
#: copy one (``sample.signal_sample_result``), and the day it was published.
SIGNAL_SAMPLE_PATHS: dict[str, str] = {
    "es": "/ejemplo-senal",
    "en": "/en/sample-signal",
    "pt": "/pt/exemplo-sinal",
}
SIGNAL_SAMPLE_PUBLISHED = "2026-10-09"
#: The day the challenge calculator and its firm pages were published.
CHALLENGE_PUBLISHED = "2026-10-10"

#: Each public page as its path per language. The sitemap lists exactly these.
#: Spanish and English exist for every page; Portuguese only where translated.
PUBLIC_PAGES: tuple[dict[str, str], ...] = (
    {"es": "/", "en": "/en", "pt": "/pt"},
    {"es": "/ejemplo", "en": "/sample", "pt": "/pt/exemplo"},
    dict(SIGNAL_SAMPLE_PATHS),
    dict(EXAMPLES_PATH),
    {lang: guides_index_url(lang) for lang in ("es", "en", "pt")},
    {lang: articles_index_url(lang) for lang in ("es", "en", "pt")},
    *({lang: guide_url(g.slug, lang) for lang in ("es", "en", "pt")} for g in GUIDES),
    *({lang: article_url(a.key, lang) for lang in ("es", "en", "pt")} for a in ARTICLES),
    dict(METHOD_PATH),
    dict(CALCULATOR_PATH),
    dict(READING_PATH),
    dict(WINRATE_PATH),
    # The challenge calculator and one page per firm with a published preset.
    challenge_paths(),
    *(challenge_paths(firm) for firm in CHALLENGE_FIRMS),
    # The public table of every firm's rules, from the same presets (``rules_table``).
    rules_table_paths(),
    dict(TOOLS_PATH),
    dict(FAQ_PATH),
    dict(PRICING_PATH),
    *({lang: audience_url(a.slug, lang) for lang in ("es", "en", "pt")} for a in AUDIENCE_PAGES),
    dict(CHECK_PATH),
    {"es": "/terminos", "en": "/terms", "pt": "/pt/termos"},
    {"es": "/privacidad", "en": "/privacy", "pt": "/pt/privacidade"},
    # The contact page (pages.CONTACT_PATHS, kept in step by a test).
    {"es": "/contacto", "en": "/en/contact", "pt": "/pt/contato"},
    # Who is behind Rigor (about.py): the operator's published details.
    dict(ABOUT_PATH),
    # The institutional review with its request form, and its sample review
    # (``institutional``: a leaf module, so importing it here makes no cycle).
    dict(REVIEW_PATHS),
    dict(SAMPLE_PATHS),
)

#: The date of the last change to the copy every public page shares (navigation,
#: footer, titles). A page with a date of its own in the code uses that instead:
#: an article its publication date, the legal pages ``LEGAL_UPDATED``. Change it
#: whenever such shared copy changes; never per request.
SITE_UPDATED = "2026-10-08"


def _page_dates() -> dict[str, str]:
    """The pages whose date lives in the code, by path. No date is made up per URL."""
    dates = {
        article_url(article.key, lang): ARTICLE_PUBLICATION_DATES[article.key]
        for article in ARTICLES
        for lang in LOCALES
    }
    # The index changes when an article is added: its date is the newest article's.
    newest = max(ARTICLE_PUBLICATION_DATES.values())
    dates.update({articles_index_url(lang): newest for lang in LOCALES})
    dates.update({path: LEGAL_UPDATED for pages in LEGAL_PATHS.values() for path in pages.values()})
    dates.update({path: SIGNAL_SAMPLE_PUBLISHED for path in SIGNAL_SAMPLE_PATHS.values()})
    dates.update(
        {
            path: CHALLENGE_PUBLISHED
            for firm in ("", *CHALLENGE_FIRMS)
            for path in challenge_paths(firm).values()
        }
    )
    dates.update({path: RULES_TABLE_PUBLISHED for path in rules_table_paths().values()})
    # The institutional review's offer and its sample review changed together.
    institutional = (*REVIEW_PATHS.values(), *SAMPLE_PATHS.values())
    dates.update({path: OFFER_UPDATED for path in institutional})
    return dates


PAGE_DATES: dict[str, str] = _page_dates()


def page_lastmod(path: str) -> str:
    """The ``<lastmod>`` of a public ``path``: its own date, or ``SITE_UPDATED``."""
    return PAGE_DATES.get(path, SITE_UPDATED)


#: Paths crawlers are asked to skip: report URLs carry the owner's token.
DISALLOWED_PATHS: tuple[str, ...] = (
    "/audits/",
    "/webhooks/",
    "/health",
    # Every account screen in each language, with its sub-pages (kept in step
    # with account_pages.PATHS by a test; account_pt imports this module).
    "/registro",
    "/entrar",
    "/salir",
    "/cuenta",
    "/olvide",
    "/restablecer",
    "/signup",
    "/login",
    "/logout",
    "/account",
    "/forgot",
    "/reset",
    "/pt/cadastro",
    "/pt/entrar",
    "/pt/sair",
    "/pt/conta",
    "/pt/esqueci",
    "/pt/redefinir",
)

#: Private pages a crawler may fetch but must not list: the comparison of two
#: reports and the e-mail confirmation (compare.COMPARE_PATH and mail.PATHS, kept
#: in step by a test). They carry the header and stay out of ``robots.txt``, so
#: a crawler that finds a link reads the ``noindex`` instead of guessing.
NOINDEX_PATHS: tuple[str, ...] = (
    "/comparar",
    "/compare",
    "/pt/comparar",
    "/confirmar-correo",
    "/confirm-email",
    "/pt/confirmar-email",
)


def _under(path: str, prefix: str) -> bool:
    """Whether ``path`` is ``prefix`` or a page below it: ``/pt/contato`` is not
    under ``/pt/conta``."""
    if prefix.endswith("/"):
        return path.startswith(prefix)
    return path == prefix or path.startswith(prefix + "/")


def is_private_path(path: str) -> bool:
    """Whether a page at ``path`` must carry the ``noindex`` header."""
    return any(_under(path, prefix) for prefix in DISALLOWED_PATHS + NOINDEX_PATHS)


@dataclass(frozen=True)
class PageMeta:
    title: str
    description: str
    locale: str
    #: The page's path in each language, for canonical and hreflang links.
    #: Empty for pages with no fixed address (reports, errors).
    paths: dict[str, str] = field(default_factory=dict)
    index: bool = True
    og_type: str = "website"
    #: Which share card to show (see ``OG_KINDS``); "" is the site card.
    image: str = ""
    image_alt: str = ""
    #: A same-site image path for a publication; empty uses the static card.
    image_path: str = ""


#: Pixel size of the share images in ``static/`` (tools/make_og_images.py).
OG_IMAGE_SIZE = (1200, 630)
#: The share cards: the site card, the sample, one per class for a published
#: verification page and one per audience page. Each card shows fixed texts only,
#: never a figure from a client's file. Contact-led institutional pages reuse
#: the site card instead of referring to a card asset that does not exist.
OG_KINDS: tuple[str, ...] = (
    "",
    "sample",
    *(f"class-{overall}" for overall in "ABCD"),
    *(f"for-{audience.slug}" for audience in AUDIENCE_PAGES if not audience.contact_cta),
)


#: Card kinds a language has only in part: Portuguese has the site and audience
#: cards. Its class/sample source copy is ready in tools/make_og_images.py; keep
#: the English fallback until the five Portuguese PNGs are rendered and reviewed.
OG_PARTIAL_KINDS: dict[str, tuple[str, ...]] = {
    "pt": ("", *(f"for-{audience.slug}" for audience in AUDIENCE_PAGES if not audience.contact_cta))
}


def og_image_name(kind: str, locale: str) -> str:
    """The file under ``static/`` of the share card ``kind`` in ``locale``. A card a
    language does not have yet (see ``OG_PARTIAL_KINDS``) is the English one."""
    kind = kind if kind in OG_KINDS else ""
    locale = OG_IMAGE_LOCALE.get(locale, "en")
    if locale in OG_PARTIAL_KINDS and kind not in OG_PARTIAL_KINDS[locale]:
        locale = "en"
    return f"og-{kind}-{locale}.png" if kind else f"og-{locale}.png"


OG_IMAGES: tuple[str, ...] = tuple(
    dict.fromkeys(
        og_image_name(k, lang) for k in OG_KINDS for lang in sorted(set(OG_IMAGE_LOCALE.values()))
    )
)


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _json_ld(value: dict[str, Any]) -> str:
    """A non-executable JSON data block, safe even for script-closing text.

    HTML entities are not decoded in script raw text. Escape HTML delimiters
    as JSON unicode sequences here; visible copies use ``html.escape``.
    """
    payload = json.dumps(value, ensure_ascii=True, allow_nan=False).replace("<", "\\u003c")
    payload = payload.replace(">", "\\u003e").replace("&", "\\u0026")
    return f"<script type='application/ld+json'>{payload}</script>"


def article_structured_data(article: Article, locale: str, base_url: str) -> str:
    """Only editorial fields and the public breadcrumb; never arbitrary data."""
    base = base_url.rstrip("/")
    published = ARTICLE_PUBLICATION_DATES[article.key]
    detail = _json_ld(
        {
            "@context": "https://schema.org",
            "@type": "Article",
            "headline": article.text[locale].title,
            "datePublished": published,
            "dateModified": published,
            "inLanguage": locale,
            "author": {"@type": "Person", "name": "Sergio Valle"},
            "publisher": {"@type": "Organization", "name": BRAND},
            "mainEntityOfPage": base + article_url(article.key, locale),
        }
    )
    home = {"es": "/", "en": "/en", "pt": "/pt"}[locale]
    crumbs = (
        ({"es": "Inicio", "en": "Home", "pt": "Início"}[locale], home),
        (ARTICLES_COPY[locale]["eyebrow"], articles_index_url(locale)),
        (article.text[locale].title, article_url(article.key, locale)),
    )
    return detail + _json_ld(
        {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": position, "name": name, "item": base + path}
                for position, (name, path) in enumerate(crumbs, start=1)
            ],
        }
    )


def _web_application(name: str, description: str, url: str, locale: str) -> dict[str, Any]:
    """A free tool that runs in the browser; ``url`` is absolute.

    The publisher is Rigor: a tool named after a prop firm must not read as the
    firm's own in a search result."""
    return {
        "@type": "WebApplication",
        "name": name,
        "description": description,
        "url": url,
        "applicationCategory": "FinanceApplication",
        "operatingSystem": "Web",
        "isAccessibleForFree": True,
        "inLanguage": locale,
        "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
        "publisher": {"@type": "Organization", "name": BRAND},
    }


def web_application_structured_data(name: str, description: str, url: str, locale: str) -> str:
    """One free tool as a ``WebApplication``: only the texts its page shows."""
    return _json_ld(
        {"@context": "https://schema.org", **_web_application(name, description, url, locale)}
    )


def tools_structured_data(items: Sequence[tuple[str, str, str]], locale: str) -> str:
    """The free tools page as an ``ItemList`` of ``WebApplication``.

    ``items`` are (name, description, absolute URL), in the order the page shows them.
    """
    return _json_ld(
        {
            "@context": "https://schema.org",
            "@type": "ItemList",
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": position,
                    "item": _web_application(name, description, url, locale),
                }
                for position, (name, description, url) in enumerate(items, start=1)
            ],
        }
    )


def dataset_structured_data(
    name: str, description: str, url: str, locale: str, *, modified: str
) -> str:
    """A table of transcribed rules as a ``Dataset``: only the texts its page
    shows and the date of its most recent reading; the publisher is Rigor, never
    one of the firms."""
    return _json_ld(
        {
            "@context": "https://schema.org",
            "@type": "Dataset",
            "name": name,
            "description": description,
            "url": url,
            "inLanguage": locale,
            "dateModified": modified,
            "isAccessibleForFree": True,
            "creator": {"@type": "Organization", "name": BRAND},
            "publisher": {"@type": "Organization", "name": BRAND},
        }
    )


def articles_faq_structured_data(locale: str) -> str:
    return faq_structured_data(articles_index_faq(locale))


def faq_structured_data(items: tuple[tuple[str, str], ...]) -> str:
    """Serialize the same question/answer pairs that the page shows visibly."""
    return _json_ld(
        {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": question,
                    "acceptedAnswer": {"@type": "Answer", "text": answer},
                }
                for question, answer in items
            ],
        }
    )


def page_paths(path: str) -> dict[str, str]:
    """The language versions of a public ``path`` (``{}`` when it is not public)."""
    return next((dict(pair) for pair in PUBLIC_PAGES if path in pair.values()), {})


def head_meta(meta: PageMeta, *, base_url: str = "") -> str:
    """The ``<meta>`` and ``<link>`` tags for a page's ``<head>``.

    URLs are absolute when ``base_url`` is known; without it the canonical,
    alternate and ``og:url`` tags are left out rather than guessed.
    """
    locale = meta.locale if meta.locale in LOCALES else "es"
    tags = [
        f"<meta name='description' content='{_e(meta.description)}'>",
        f"<meta name='robots' content='{'index, follow' if meta.index else NOINDEX}'>",
        f"<meta property='og:title' content='{_e(meta.title)}'>",
        f"<meta property='og:description' content='{_e(meta.description)}'>",
        f"<meta property='og:type' content='{_e(meta.og_type)}'>",
        f"<meta property='og:site_name' content='{_e(SITE_NAME[locale])}'>",
        f"<meta property='og:locale' content='{OG_LOCALE[locale]}'>",
        f"<meta name='twitter:card' content='{'summary_large_image' if base_url else 'summary'}'>",
        f"<meta name='twitter:title' content='{_e(meta.title)}'>",
        f"<meta name='twitter:description' content='{_e(meta.description)}'>",
    ]
    base = base_url.rstrip("/")
    if base:
        # Messaging apps need an absolute URL to show a picture with the link.
        image = (
            f"{base}{meta.image_path}"
            if meta.image_path
            else f"{base}/static/{og_image_name(meta.image, meta.locale)}"
        )
        tags += [
            f"<meta property='og:image' content='{_e(image)}'>",
            "<meta property='og:image:type' content='image/png'>",
            f"<meta property='og:image:width' content='{OG_IMAGE_SIZE[0]}'>",
            f"<meta property='og:image:height' content='{OG_IMAGE_SIZE[1]}'>",
            f"<meta property='og:image:alt' content='{_e(meta.image_alt or SITE_NAME[locale])}'>",
            f"<meta name='twitter:image' content='{_e(image)}'>",
        ]
    own = meta.paths.get(locale)
    if base and own:
        tags.append(f"<link rel='canonical' href='{_e(base + own)}'>")
        tags.append(f"<meta property='og:url' content='{_e(base + own)}'>")
        if meta.index:
            for lang, path in sorted(meta.paths.items()):
                tags.append(
                    f"<link rel='alternate' hreflang='{_e(lang)}' href='{_e(base + path)}'>"
                )
            default = meta.paths.get("es", own)
            tags.append(f"<link rel='alternate' hreflang='x-default' href='{_e(base + default)}'>")
    return "".join(tags)


def private_meta(title: str, locale: str, description: str = "") -> str:
    """Tags for a page that must never be indexed or previewed with detail.

    ``description`` is a fixed sentence about the page; without it the title is used."""
    return head_meta(
        PageMeta(title=title, description=description or title, locale=locale, index=False)
    )


def robots_txt(base_url: str) -> str:
    # A rule matches by prefix, so ``Disallow: /pt/conta`` would also close the
    # public ``/pt/contato``: such a page gets its own, longer ``Allow`` line,
    # listed first for the crawlers that stop at the first rule that matches.
    allowed = sorted(
        {
            path
            for pair in PUBLIC_PAGES
            for path in pair.values()
            if path.startswith(DISALLOWED_PATHS) and not is_private_path(path)
        }
    )
    lines = [
        "User-agent: *",
        *(f"Allow: {path}" for path in allowed),
        *(f"Disallow: {path}" for path in DISALLOWED_PATHS),
        "Allow: /",
    ]
    lines += ["", f"Sitemap: {base_url.rstrip('/')}/sitemap.xml", ""]
    return "\n".join(lines)


def sitemap_xml(base_url: str) -> str:
    """Every public page in each of its languages, each with its date and alternates.

    ``<lastmod>`` goes right after ``<loc>``, as the sitemap schema orders them."""
    base = _e(base_url.rstrip("/"))
    urls = []
    for pair in PUBLIC_PAGES:
        langs = [lang for lang in LOCALES if lang in pair]
        alternates = "".join(
            f"<xhtml:link rel='alternate' hreflang='{lang}' href='{base}{_e(pair[lang])}'/>"
            for lang in langs
        )
        # The same default the pages declare in their head (``head_meta``).
        default = _e(pair.get("es", pair[langs[0]]))
        alternates += f"<xhtml:link rel='alternate' hreflang='x-default' href='{base}{default}'/>"
        for lang in langs:
            urls.append(
                f"<url><loc>{base}{_e(pair[lang])}</loc>"
                f"<lastmod>{page_lastmod(pair[lang])}</lastmod>{alternates}</url>"
            )
    return (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9' "
        "xmlns:xhtml='http://www.w3.org/1999/xhtml'>" + "".join(urls) + "</urlset>"
    )


__all__ = [
    "BRAND",
    "CHALLENGE_PUBLISHED",
    "DISALLOWED_PATHS",
    "NOINDEX",
    "NOINDEX_PATHS",
    "OG_IMAGE_LOCALE",
    "OG_LOCALE",
    "PAGE_DATES",
    "PUBLIC_PAGES",
    "RULES_TABLE_PUBLISHED",
    "SITE_NAME",
    "SIGNAL_SAMPLE_PATHS",
    "SIGNAL_SAMPLE_PUBLISHED",
    "SITE_UPDATED",
    "TAGLINE",
    "PageMeta",
    "dataset_structured_data",
    "head_meta",
    "is_private_path",
    "page_lastmod",
    "page_paths",
    "private_meta",
    "robots_txt",
    "sitemap_xml",
    "tools_structured_data",
    "web_application_structured_data",
]
