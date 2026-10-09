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
#: the page of a report uploaded in Spanish does.
SAMPLE_PUBLICATION_LOCALE = "es"

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
#: The notice's link to the sample's full report.
SAMPLE_REPORT_LINK: dict[str, str] = {
    "es": "Ver el informe completo de este ejemplo",
    "en": "See this sample's full report",
    "pt": "Ver o relatório completo deste exemplo",
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
#: The line in each sample report's band: the public page of that very report.
SAMPLE_BAND_LINK: dict[str, str] = {
    "es": "Mira cómo se ve la página pública de este informe, con su sello y su tarjeta",
    "en": "See this report's public page, with its badge and card",
    "pt": "Veja como fica a página pública deste relatório, com o selo e o cartão",
}


def _lang(locale: str) -> str:
    return locale if locale in PUBLIC_PAGE_LINK else "es"


def _e(value: str) -> str:
    return html.escape(value, quote=True)


def sample_public_id(report_kind: str) -> str:
    """The sample whose public page fits a report: an account history (``report_kind``
    "account") is shown the signal's, anything else the backtest's."""
    return SAMPLE_PUBLIC_IDS["signal" if report_kind == "account" else "backtest"]


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


def sample_notice_html(public_id: str, locale: str) -> str:
    """The notice on top of a sample's public page; empty for any other id, so a
    publication's page never carries one."""
    kind = SAMPLE_KIND_BY_PUBLIC_ID.get(public_id)
    if kind is None:
        return ""
    # The sample reports' addresses live with their pages (imported here, not at the
    # top, so the pages can import this module).
    from quant_trade.audit.pages import SAMPLE_PAGE_PATHS
    from quant_trade.audit.seo import SIGNAL_SAMPLE_PATHS

    lang = _lang(locale)
    report = (SIGNAL_SAMPLE_PATHS if kind == "signal" else SAMPLE_PAGE_PATHS)[lang]
    return (
        "<div class='notice sample-publication' role='note'>"
        f"{_e(SAMPLE_PUBLICATION_NOTICE[kind][lang])} "
        f"<a href='{_e(report)}'>{_e(SAMPLE_REPORT_LINK[lang])}</a></div>"
    )


@dataclass(frozen=True)
class SamplePublication:
    """What ``/v`` reads of a publication and of its audit record, for a sample's
    page: its id, its date (the sample's audit date) and its class."""

    public_id: str
    created_at: str
    overall_class: str


def sample_publication(
    public_id: str, result: AuditResult
) -> tuple[SamplePublication, dict[str, Any], str]:
    """A sample's publication, the view its page reads and the result's SHA-256:
    the view a retention purge keeps (``store.public_view``), built in memory from
    the JSON an upload stores (``report.to_json``, keys sorted), so the page lists
    what it lists in the order a real publication's page does."""
    from quant_trade.audit.report import to_json
    from quant_trade.audit.store import public_view

    view, digest = public_view(to_json(result))
    stamp = str(view.get("generated_at_utc", ""))
    publication = SamplePublication(
        public_id=public_id,
        created_at=stamp,
        overall_class=str(view["verdict"]["overall"]),
    )
    return publication, view, digest


__all__ = [
    "PUBLIC_ID_LENGTH",
    "PUBLIC_PAGES_LINE",
    "PUBLIC_PAGE_LINK",
    "SAMPLE_BAND_LINK",
    "SAMPLE_KIND_BY_PUBLIC_ID",
    "SAMPLE_PUBLICATION_LOCALE",
    "SAMPLE_PUBLICATION_NOTICE",
    "SAMPLE_PUBLIC_IDS",
    "SAMPLE_REPORT_LINK",
    "SamplePublication",
    "public_pages_line",
    "sample_notice_html",
    "sample_public_id",
    "sample_public_path",
    "sample_publication",
]
