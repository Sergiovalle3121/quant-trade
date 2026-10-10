"""The public page of each public sample: ``/v/ejemplo`` and ``/v/ejemplo-senal``.

A provider pays for the public page, its badge and its card, and they are the
only part of Rigor that reaches the provider's own clients; until now nobody
could see them without uploading a file first. Each public sample
(``sample.py``) gets the page a real publication of its report would get:
``web`` answers ``/v/ejemplo`` (``sample.sample_result``) and
``/v/ejemplo-senal`` (``sample.signal_sample_result``) through the same routes,
functions and caching as ``/v/{public_id}`` (``pages.verification_page``,
``pages.badge_svg``, ``pages.verification_card_svg``), from the view a
retention purge keeps (``store.public_view``) of the sample's result, with the
synthetic-data notice on top. Nothing is read from or written to the database.

Only what would pass the sample off as someone's real audit is said its own way
(``sample_page``): the tab title and the link preview say it is a sample, the
share text is not in the first person and carries its own funnel tag, and the
badge's code is shown as the sample's, without a copy button. The page is
dated the day it was published, as a publication's page is.

The two ids are reserved by the format of a real one: ``Store.publish`` draws
``secrets.token_urlsafe(9)``, always ``PUBLIC_ID_LENGTH`` (12) characters of
``A-Z a-z 0-9 _ -``, while "ejemplo" has 7 and "ejemplo-senal" 13. ``web``
also answers them before any lookup, so no stored row could take their place.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from quant_trade.audit.schema import AuditResult

#: Each public sample's reserved public id, by sample kind (``report.SAMPLE_KINDS``).
SAMPLE_PUBLIC_IDS: dict[str, str] = {"backtest": "ejemplo", "signal": "ejemplo-senal"}
#: The other way round: which sample a reserved id shows.
SAMPLE_KIND_BY_PUBLIC_ID: dict[str, str] = {
    public_id: kind for kind, public_id in SAMPLE_PUBLIC_IDS.items()
}
#: The length of every real public id: ``secrets.token_urlsafe(9)`` encodes 9 random
#: bytes as 12 base64url characters, without padding.
PUBLIC_ID_LENGTH = 12
#: A publication has one result, so one hash, in every language of its page: each
#: sample's page comes from its Spanish report (``/ejemplo``, ``/ejemplo-senal``), as
#: the page of a report uploaded in Spanish does. The English and Portuguese reports
#: are other results with other hashes, so the page says so in those languages
#: (``SAMPLE_SPANISH_SOURCE``) and its notice links the Spanish report.
SAMPLE_PUBLICATION_LOCALE = "es"
#: The day both sample pages were published, shown as "Published" (a publication's
#: own date, never the audit's): a bare date, so no time of day is made up.
SAMPLE_PAGES_PUBLISHED = "2026-10-09"
#: The funnel tag of a shared sample page (``funnel.REF_TAGS``), so its visits never
#: count as a shared publication's ("share").
SAMPLE_SHARE_REF = "v-ejemplo"
#: The identifier a reader sees for each sample, in each language: on its report
#: and PDF (``report.LABELS[locale]['audit_id']``, in place of the stored id
#: ``check.SAMPLE_AUDIT_ID``, which ``/comprobar`` keeps reading) and on its public
#: page. The PDFs' file names use the same words.
SAMPLE_SHOWN_IDS: dict[str, dict[str, str]] = {
    "backtest": {"es": "ejemplo", "en": "sample", "pt": "exemplo"},
    "signal": {"es": "ejemplo-senal", "en": "sample-signal", "pt": "exemplo-sinal"},
}
#: Beside the holdout seal's identifier, where the report keeps the stored id: the
#: seal's SHA-256 is computed with it, so it is never swapped, only explained when
#: the report shows the sample under another word (``SAMPLE_SHOWN_IDS``).
SAMPLE_SEAL_NOTE: dict[str, str] = {
    "es": (
        "el identificador con el que se guardó este ejemplo y con el que se calcula su "
        "sello; el resto del informe lo muestra como «{shown}»"
    ),
    "en": (
        "the identifier this sample was stored under, which its seal is computed "
        "with; the rest of the report shows it as “{shown}”"
    ),
    "pt": (
        "o identificador com que este exemplo foi guardado e com o qual o selo é "
        "calculado; o resto do relatório o mostra como «{shown}»"
    ),
}

#: The notice on top of a sample's public page: what the page is, then the
#: synthetic-data notice of the sample reports.
SAMPLE_PUBLICATION_NOTICE: dict[str, dict[str, str]] = {
    "backtest": {
        "es": (
            "Página pública de ejemplo, hecha con datos sintéticos generados por computadora: "
            "no es la cuenta ni la estrategia de nadie. Así se ve la página que publicas desde "
            "tu informe, con su sello y su tarjeta."
        ),
        "en": (
            "Sample public page, built from computer-generated synthetic data: it is nobody's "
            "account or strategy. This is what the page you publish from your report looks "
            "like, with its badge and card."
        ),
        "pt": (
            "Página pública de exemplo, feita com dados sintéticos gerados por computador: não "
            "é a conta nem a estratégia de ninguém. Assim fica a página que você publica a "
            "partir do seu relatório, com o selo e o cartão."
        ),
    },
    "signal": {
        "es": (
            "Página pública de ejemplo de una señal inventada, hecha con datos sintéticos "
            "generados por computadora: no es la cuenta ni la estrategia de nadie. Así se ve la "
            "página que publica un proveedor desde el informe de su cuenta, con su sello y su "
            "tarjeta."
        ),
        "en": (
            "Sample public page of a made-up signal, built from computer-generated synthetic "
            "data: it is nobody's account or strategy. This is what the page a provider "
            "publishes from their account's report looks like, with its badge and card."
        ),
        "pt": (
            "Página pública de exemplo de um sinal inventado, feita com dados sintéticos "
            "gerados por computador: não é a conta nem a estratégia de ninguém. Assim fica a "
            "página que um fornecedor publica a partir do relatório da sua conta, com o selo e "
            "o cartão."
        ),
    },
}
#: Where the page comes from, after the notice: in Spanish it is the report itself.
SAMPLE_SPANISH_SOURCE: dict[str, str] = {
    "es": "",
    "en": (
        "It is made from the Spanish version of the sample, so it shows the SHA-256 of that report."
    ),
    "pt": (
        "Ela é feita a partir da versão em espanhol do exemplo, por isso mostra o SHA-256 "
        "desse relatório."
    ),
}
#: The notice's link to the report the page is made from (the Spanish one).
SAMPLE_REPORT_LINK: dict[str, str] = {
    "es": "Ver el informe completo de este ejemplo",
    "en": "See the Spanish report it is made from",
    "pt": "Ver o relatório em espanhol de onde ela sai",
}
#: The line under the report's publish button, to the sample of the same kind.
PUBLIC_PAGE_LINK: dict[str, str] = {
    "es": "Mira cómo se ve una página pública",
    "en": "See what a public page looks like",
    "pt": "Veja como fica uma página pública",
}
#: The same line with both samples, for the FAQ and the pages for providers.
PUBLIC_PAGES_LINE: dict[str, dict[str, str]] = {
    "es": {
        "lead": "Mira cómo se ve una página pública:",
        "backtest": "la de un backtest",
        "or": "o",
        "signal": "la de una cuenta de señales",
    },
    "en": {
        "lead": "See what a public page looks like:",
        "backtest": "a backtest's",
        "or": "or",
        "signal": "a signal account's",
    },
    "pt": {
        "lead": "Veja como fica uma página pública:",
        "backtest": "a de um backtest",
        "or": "ou",
        "signal": "a de uma conta de sinais",
    },
}
#: The line in each sample report's band: the public page of that sample. Only the
#: Spanish report is the very one the page shows; the others say where it comes from.
SAMPLE_BAND_LINK: dict[str, str] = {
    "es": "Mira cómo se ve la página pública de este informe, con su sello y su tarjeta",
    "en": (
        "See the public page of this sample, made from its Spanish version, with its badge and card"
    ),
    "pt": (
        "Veja a página pública deste exemplo, feita a partir da versão em espanhol, com o "
        "selo e o cartão"
    ),
}
#: The word in front of a sample page's tab title (and the title its link preview shows).
SAMPLE_TITLE_WORD: dict[str, str] = {"es": "Ejemplo", "en": "Sample", "pt": "Exemplo"}
#: The words in front of a sample page's link preview description.
SAMPLE_META_LEAD: dict[str, str] = {
    "es": "Ejemplo con datos sintéticos",
    "en": "Sample with synthetic data",
    "pt": "Exemplo com dados sintéticos",
}
#: A sample page's share text: what the page is, never "I audited my ...".
SAMPLE_SHARE_TEXT: dict[str, str] = {
    "es": "Así se ve una página pública de Rigor (ejemplo con datos sintéticos): {url}",
    "en": "This is what a Rigor public page looks like (a sample with synthetic data): {url}",
    "pt": "Assim fica uma página pública do Rigor (exemplo com dados sintéticos): {url}",
}
#: Over a sample page's badge code, instead of the invitation to copy it.
SAMPLE_BADGE_HELP: dict[str, str] = {
    "es": (
        "Así queda el código del sello en tu página, para copiarlo en tu web, Telegram o "
        "foro. Este es el del ejemplo: no lo copies; el tuyo lleva tu clase, tu fecha y tu ID."
    ),
    "en": (
        "This is how the badge code looks on your page, to copy to your site, Telegram or "
        "forum. This one is the sample's: do not copy it; yours carries your class, date "
        "and ID."
    ),
    "pt": (
        "Assim fica o código do selo na sua página, para copiar no seu site, Telegram ou "
        "fórum. Este é o do exemplo: não o copie; o seu leva a sua classe, a sua data e o "
        "seu ID."
    ),
}


def _lang(locale: str) -> str:
    return locale if locale in PUBLIC_PAGE_LINK else "es"


def _e(value: str) -> str:
    return html.escape(value, quote=True)


def sample_public_id(report_kind: str) -> str:
    """The sample whose public page fits a report: an account history or a fund's
    track record (``report_kind`` "account" or "fund": a real history, whose card is
    drawn from its own SVG) is shown the signal's, a backtest the backtest's."""
    return SAMPLE_PUBLIC_IDS["signal" if report_kind in ("account", "fund") else "backtest"]


def sample_public_path(public_id: str, locale: str) -> str:
    """A public page's address in ``locale``; Spanish has no suffix, as a badge's link."""
    lang = _lang(locale)
    path = f"/v/{public_id}"
    return path if lang == "es" else f"{path}?lang={lang}"


def public_pages_line(locale: str, *, css: str = "") -> str:
    """One paragraph linking both samples' public pages."""
    lang = _lang(locale)
    words = PUBLIC_PAGES_LINE[lang]
    links = {
        kind: f"<a href='{_e(sample_public_path(public_id, lang))}'>{_e(words[kind])}</a>"
        for kind, public_id in SAMPLE_PUBLIC_IDS.items()
    }
    attribute = f" class='{_e(css)}'" if css else ""
    return (
        f"<p{attribute}>{_e(words['lead'])} {links['backtest']} {_e(words['or'])} "
        f"{links['signal']}.</p>"
    )


def sample_report_path(public_id: str) -> str:
    """The report a sample's page is made from, whose hash the page shows: the
    sample's Spanish report (``SAMPLE_PUBLICATION_LOCALE``), in every language."""
    # The sample reports' addresses live with their pages (imported here, not at the
    # top, so the pages can import this module).
    from quant_trade.audit.pages import SAMPLE_PAGE_PATHS
    from quant_trade.audit.seo import SIGNAL_SAMPLE_PATHS

    kind = SAMPLE_KIND_BY_PUBLIC_ID[public_id]
    paths = SIGNAL_SAMPLE_PATHS if kind == "signal" else SAMPLE_PAGE_PATHS
    return paths[SAMPLE_PUBLICATION_LOCALE]


def sample_notice_html(public_id: str, locale: str) -> str:
    """The notice on top of a sample's public page; empty for any other id, so a
    publication's page never carries one."""
    kind = SAMPLE_KIND_BY_PUBLIC_ID.get(public_id)
    if kind is None:
        return ""
    lang = _lang(locale)
    words = " ".join(
        part
        for part in (SAMPLE_PUBLICATION_NOTICE[kind][lang], SAMPLE_SPANISH_SOURCE[lang])
        if part
    )
    return (
        "<div class='notice sample-publication' role='note'>"
        f"{_e(words)} "
        f"<a href='{_e(sample_report_path(public_id))}'>{_e(SAMPLE_REPORT_LINK[lang])}</a></div>"
    )


@dataclass(frozen=True)
class SamplePage:
    """What a sample's public page says its own way (``pages.verification_page``):
    the notice on top, the word in front of its title and of its link preview, the
    share text and its funnel tag, and the words over its badge code."""

    notice_html: str
    title_word: str
    meta_lead: str
    share_template: str
    share_ref: str
    badge_help: str
    #: The identifier its report shows (``SAMPLE_SHOWN_IDS``), in place of the page's id.
    shown_id: str = ""


def sample_page(public_id: str, locale: str) -> SamplePage | None:
    """A sample's own words for its page in ``locale``; ``None`` for any other id, so
    a publication's page never changes."""
    if public_id not in SAMPLE_KIND_BY_PUBLIC_ID:
        return None
    lang = _lang(locale)
    return SamplePage(
        notice_html=sample_notice_html(public_id, lang),
        title_word=SAMPLE_TITLE_WORD[lang],
        meta_lead=SAMPLE_META_LEAD[lang],
        share_template=SAMPLE_SHARE_TEXT[lang],
        share_ref=SAMPLE_SHARE_REF,
        badge_help=SAMPLE_BADGE_HELP[lang],
        shown_id=SAMPLE_SHOWN_IDS[SAMPLE_KIND_BY_PUBLIC_ID[public_id]][lang],
    )


def show_sample_id(page: str, kind: str, locale: str) -> str:
    """A sample report's HTML with its identifier as the reader sees it everywhere
    (``SAMPLE_SHOWN_IDS``): the report prints the stored id, ``check.SAMPLE_AUDIT_ID``,
    after ``report.LABELS[locale]['audit_id']``. Only those words change; nothing the
    report measured does, and the stored id stays what ``/comprobar`` reads.

    The holdout seal's identifier keeps the stored id, since its SHA-256 is computed
    with it; when the shown word differs, ``SAMPLE_SEAL_NOTE`` says so beside it."""
    from quant_trade.audit.check import SAMPLE_AUDIT_ID
    from quant_trade.audit.report import KEY_LABELS, LABELS

    lang = _lang(locale)
    label = html.escape(LABELS[lang]["audit_id"], quote=True)
    word = SAMPLE_SHOWN_IDS[kind][lang]
    shown = html.escape(word, quote=True)
    page = page.replace(f"<span>{label} {SAMPLE_AUDIT_ID}", f"<span>{label} {shown}")
    if word == SAMPLE_AUDIT_ID:
        return page
    seal = html.escape(KEY_LABELS[lang]["seal_id"], quote=True)
    row = f"<tr><td>{seal}</td><td><code>{SAMPLE_AUDIT_ID}</code>"
    note = html.escape(SAMPLE_SEAL_NOTE[lang].format(shown=word), quote=True)
    return page.replace(row, f"{row} <span class='muted'>({note})</span>")


@dataclass(frozen=True)
class SamplePublication:
    """What ``/v`` reads of a publication, for a sample's page: its id and the day
    it was published (``SAMPLE_PAGES_PUBLISHED``)."""

    public_id: str
    created_at: str


@dataclass(frozen=True)
class SampleAudit:
    """What ``/v`` reads of a publication's audit record, for a sample's badge: the
    audit's date (the sample's fixed clock) and its class."""

    created_at: str
    overall_class: str


def sample_publication(
    public_id: str, result: AuditResult
) -> tuple[SamplePublication, SampleAudit, dict[str, Any], str]:
    """A sample's publication, its audit record, the view its page reads and the
    result's SHA-256: the view a retention purge keeps (``store.public_view``), built
    in memory from the JSON an upload stores (``report.to_json``, keys sorted), so the
    page lists what it lists in the order a real publication's page does."""
    from quant_trade.audit.report import to_json
    from quant_trade.audit.store import public_view

    view, digest = public_view(to_json(result))
    publication = SamplePublication(public_id=public_id, created_at=SAMPLE_PAGES_PUBLISHED)
    record = SampleAudit(
        created_at=str(view.get("generated_at_utc", "")),
        overall_class=str(view["verdict"]["overall"]),
    )
    return publication, record, view, digest


__all__ = [
    "PUBLIC_ID_LENGTH",
    "PUBLIC_PAGES_LINE",
    "PUBLIC_PAGE_LINK",
    "SAMPLE_BADGE_HELP",
    "SAMPLE_BAND_LINK",
    "SAMPLE_KIND_BY_PUBLIC_ID",
    "SAMPLE_META_LEAD",
    "SAMPLE_PAGES_PUBLISHED",
    "SAMPLE_PUBLICATION_LOCALE",
    "SAMPLE_PUBLICATION_NOTICE",
    "SAMPLE_PUBLIC_IDS",
    "SAMPLE_REPORT_LINK",
    "SAMPLE_SEAL_NOTE",
    "SAMPLE_SHARE_REF",
    "SAMPLE_SHARE_TEXT",
    "SAMPLE_SHOWN_IDS",
    "SAMPLE_SPANISH_SOURCE",
    "SAMPLE_TITLE_WORD",
    "SampleAudit",
    "SamplePage",
    "SamplePublication",
    "public_pages_line",
    "sample_notice_html",
    "sample_page",
    "sample_public_id",
    "sample_public_path",
    "sample_publication",
    "sample_report_path",
    "show_sample_id",
]
