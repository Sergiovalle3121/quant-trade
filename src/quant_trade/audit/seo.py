"""Search and link-preview metadata for the audit site.

Public pages (landing, sample, guides, terms, privacy) get a title, a
description, a canonical URL, their other-language alternate and Open Graph
tags, and are the only pages listed in ``sitemap.xml``. Private pages (a
client's report or unpaid preview, errors) are ``noindex``, and
``robots.txt`` keeps crawlers out of ``/audits/``, where report URLs carry
the owner's token. A public verification page previews its class and date
when shared, and is ``noindex`` so an unpublished audit does not linger in
search results.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field

from quant_trade.audit.audiences import AUDIENCE_PAGES, audience_url
from quant_trade.audit.guides import GUIDES, guide_url, guides_index_url
from quant_trade.audit.method import METHOD_PATH

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
OG_LOCALE: dict[str, str] = {"es": "es_ES", "en": "en_US", "pt": "pt_BR"}
#: The share picture per language.
OG_IMAGE_LOCALE: dict[str, str] = {"es": "es", "en": "en", "pt": "pt"}

NOINDEX = "noindex, nofollow"

#: Each public page as its path per language. The sitemap lists exactly these.
#: Spanish and English exist for every page; Portuguese only where translated.
PUBLIC_PAGES: tuple[dict[str, str], ...] = (
    {"es": "/", "en": "/en", "pt": "/pt"},
    {"es": "/ejemplo", "en": "/sample"},
    {lang: guides_index_url(lang) for lang in ("es", "en", "pt")},
    *({lang: guide_url(g.slug, lang) for lang in ("es", "en", "pt")} for g in GUIDES),
    dict(METHOD_PATH),
    *({lang: audience_url(a.slug, lang) for lang in ("es", "en", "pt")} for a in AUDIENCE_PAGES),
    {"es": "/comprobar", "en": "/check"},
    {"es": "/terminos", "en": "/terms"},
    {"es": "/privacidad", "en": "/privacy"},
)

#: Paths crawlers are asked to skip: report URLs carry the owner's token.
DISALLOWED_PATHS: tuple[str, ...] = (
    "/audits/",
    "/webhooks/",
    "/health",
    "/cuenta",
    "/account",
    "/restablecer",
    "/reset",
)


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


#: Pixel size of the share images in ``static/`` (tools/make_og_images.py).
OG_IMAGE_SIZE = (1200, 630)
#: The share cards: the site card, the sample, one per class for a published
#: verification page and one per audience page. Each card shows fixed texts only,
#: never a figure from a client's file.
OG_KINDS: tuple[str, ...] = (
    "",
    "sample",
    *(f"class-{overall}" for overall in "ABCD"),
    *(f"for-{audience.slug}" for audience in AUDIENCE_PAGES),
)


#: Card kinds a language has only in part: Portuguese has the site card and the
#: audience cards; its verification and sample cards wait for a Portuguese class
#: sentence and notice, and show the English card until then.
OG_PARTIAL_KINDS: dict[str, tuple[str, ...]] = {
    "pt": ("", *(f"for-{audience.slug}" for audience in AUDIENCE_PAGES))
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
        image = f"{base}/static/{og_image_name(meta.image, meta.locale)}"
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


def private_meta(title: str, locale: str) -> str:
    """Tags for a page that must never be indexed or previewed with detail."""
    return head_meta(PageMeta(title=title, description=title, locale=locale, index=False))


def robots_txt(base_url: str) -> str:
    lines = ["User-agent: *", *(f"Disallow: {path}" for path in DISALLOWED_PATHS), "Allow: /"]
    lines += ["", f"Sitemap: {base_url.rstrip('/')}/sitemap.xml", ""]
    return "\n".join(lines)


def sitemap_xml(base_url: str) -> str:
    """Every public page in each of its languages, each with its alternates."""
    base = _e(base_url.rstrip("/"))
    urls = []
    for pair in PUBLIC_PAGES:
        langs = [lang for lang in LOCALES if lang in pair]
        alternates = "".join(
            f"<xhtml:link rel='alternate' hreflang='{lang}' href='{base}{_e(pair[lang])}'/>"
            for lang in langs
        )
        for lang in langs:
            urls.append(f"<url><loc>{base}{_e(pair[lang])}</loc>{alternates}</url>")
    return (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9' "
        "xmlns:xhtml='http://www.w3.org/1999/xhtml'>" + "".join(urls) + "</urlset>"
    )


__all__ = [
    "BRAND",
    "DISALLOWED_PATHS",
    "NOINDEX",
    "OG_IMAGE_LOCALE",
    "OG_LOCALE",
    "PUBLIC_PAGES",
    "SITE_NAME",
    "TAGLINE",
    "PageMeta",
    "head_meta",
    "page_paths",
    "private_meta",
    "robots_txt",
    "sitemap_xml",
]
