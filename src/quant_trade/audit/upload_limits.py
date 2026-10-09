"""The upload size limits as a customer reads them, in one sentence from the settings.

``POST /audits`` takes every file up to ``AuditSettings.max_upload_bytes``. A field
that may carry a platform report takes ``schema.REPORT_SIZE_FACTOR`` times that
(MetaTrader writes its HTML reports in UTF-16, two bytes a character), and the
importers read at most ``schema.MAX_REPORT_BYTES`` of one. The questions page, the
MetaTrader 5 guide and the upload form print this same sentence, with what to do
when a file is larger, so none of them can drift from the limits the service applies.
"""

from __future__ import annotations

from quant_trade.audit.schema import MAX_REPORT_BYTES, MAX_UPLOAD_BYTES, REPORT_SIZE_FACTOR

#: The limits, then what to do with a larger file. ``{general}`` and ``{report}`` are
#: sizes such as "5 MB", rounded to one decimal at most.
LIMIT_COPY: dict[str, str] = {
    "es": (
        "Límite: {general} por archivo; los informes de plataforma, como el HTML de "
        "MetaTrader (viene en UTF-16), hasta {report}. Si tu archivo pasa del límite, "
        "recorta el periodo o, si tu plataforma la tiene, sube su exportación CSV."
    ),
    "en": (
        "Limit: {general} per file; platform reports, such as MetaTrader's HTML (written "
        "in UTF-16), up to {report}. If your file is over the limit, shorten the period "
        "or, if your platform has one, upload its CSV export."
    ),
    "pt": (
        "Limite: {general} por arquivo; os relatórios de plataforma, como o HTML do "
        "MetaTrader (vem em UTF-16), até {report}. Se o seu arquivo passar do limite, "
        "encurte o período ou, se a sua plataforma tiver, envie a exportação CSV dela."
    ),
}


def upload_limits(max_upload_bytes: int = MAX_UPLOAD_BYTES) -> tuple[int, int]:
    """``(any file, a platform report)`` in bytes, as ``POST /audits`` and the
    importers apply them for the configured ``max_upload_bytes``."""
    return max_upload_bytes, min(max_upload_bytes * REPORT_SIZE_FACTOR, MAX_REPORT_BYTES)


def megabytes(size: int, locale: str = "es") -> str:
    """Bytes as a reader says them: "5 MB", "7.3 MB" in English, "7,3 MB" in es and pt."""
    text = f"{size / 1_000_000:.1f}".rstrip("0").rstrip(".")
    return (text if locale == "en" else text.replace(".", ",")) + " MB"


def upload_limit_text(max_upload_bytes: int = MAX_UPLOAD_BYTES, locale: str = "es") -> str:
    """The limits sentence and what to do with a larger file, in ``locale``."""
    locale = locale if locale in LIMIT_COPY else "es"
    general, report = upload_limits(max_upload_bytes)
    return LIMIT_COPY[locale].format(
        general=megabytes(general, locale), report=megabytes(report, locale)
    )


__all__ = ["LIMIT_COPY", "megabytes", "upload_limit_text", "upload_limits"]
