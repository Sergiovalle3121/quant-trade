"""The upload size limits as a customer reads them, field by field, from the settings.

``POST /audits`` takes each file up to ``AuditSettings.max_upload_bytes``; the fields
that may carry a platform report (``web.REPORT_FIELDS``: the report, the curve, the
account statement and the optimisation export) take ``schema.REPORT_SIZE_FACTOR``
times that. The readers then apply their own ceilings, which do not move with the
setting: the importers read at most ``schema.MAX_REPORT_BYTES`` of a report, an
account statement or an optimisation export, and the CSV reader
(``schema._read_csv``) at most ``schema.MAX_UPLOAD_BYTES`` of a curve, a return
series, a trade list, a benchmark or a variant matrix. Each limit said here is the
smaller of the two, so a larger setting never promises a size a reader refuses.

The questions page and the upload form print the whole sentence; each export guide
prints the limit of the field its file goes in. None of them can drift from what
the service applies.
"""

from __future__ import annotations

from typing import NamedTuple

from quant_trade.audit.schema import MAX_REPORT_BYTES, MAX_UPLOAD_BYTES, REPORT_SIZE_FACTOR


class UploadLimits(NamedTuple):
    """The bytes a file may have, by what it is and where it goes."""

    #: "Your platform report" (an HTML, XLSX, CSV or PDF export), the account
    #: statement and the optimisation export: what the importers read.
    report: int
    #: An equity curve or a return series, in the curve field or the report field.
    series: int
    #: The closed trades, the benchmark and the variant matrix.
    other: int


#: Which of ``UploadLimits`` each upload field of ``POST /audits`` takes for its own
#: kind of file. A platform report dropped in the curve field is read as the report,
#: with the report's limit, as the field's own help says.
FIELD_LIMITS: dict[str, str] = {
    "report": "report",
    "live": "report",
    "optimization": "report",
    "equity": "series",
    "trades": "other",
    "benchmark": "other",
    "variants": "other",
}

#: The sentence, by field. ``{report}``, ``{series}`` and ``{other}`` are sizes such
#: as "5 MB", rounded to one decimal at most; ``merged`` is said when the last two
#: are the same size. Only what to do with a larger file follows: a shorter period.
LIMIT_COPY: dict[str, dict[str, str]] = {
    "es": {
        "lead": (
            "Límites por campo: «Informe de tu plataforma» (HTML, XLSX, CSV o PDF), estado "
            "de cuenta y exportación de optimización, hasta {report}; "
        ),
        "split": (
            "una curva de equity o una serie de retornos, hasta {series}; operaciones "
            "cerradas, benchmark y variantes, hasta {other}."
        ),
        "merged": (
            "una curva de equity o una serie de retornos, operaciones cerradas, benchmark "
            "y variantes, hasta {other}."
        ),
        "shorten": " Si tu archivo pasa del límite, recorta el periodo.",
        "guide": "Límite: hasta {limit} por archivo.",
    },
    "en": {
        "lead": (
            "Limits per field: “Your platform report” (HTML, XLSX, CSV or PDF), account "
            "statement and optimisation export, up to {report}; "
        ),
        "split": (
            "an equity curve or a return series, up to {series}; closed trades, benchmark "
            "and variants, up to {other}."
        ),
        "merged": (
            "an equity curve or a return series, closed trades, benchmark and variants, up "
            "to {other}."
        ),
        "shorten": " If your file is over the limit, shorten the period.",
        "guide": "Limit: up to {limit} per file.",
    },
    "pt": {
        "lead": (
            "Limites por campo: «Relatório da sua plataforma» (HTML, XLSX, CSV ou PDF), "
            "extrato da conta e exportação de otimização, até {report}; "
        ),
        "split": (
            "uma curva de equity ou uma série de retornos, até {series}; operações "
            "fechadas, benchmark e variantes, até {other}."
        ),
        "merged": (
            "uma curva de equity ou uma série de retornos, operações fechadas, benchmark e "
            "variantes, até {other}."
        ),
        "shorten": " Se o seu arquivo passar do limite, encurte o período.",
        "guide": "Limite: até {limit} por arquivo.",
    },
}


def upload_limits(max_upload_bytes: int = MAX_UPLOAD_BYTES) -> UploadLimits:
    """The bytes ``POST /audits`` and the readers together accept for the configured
    ``max_upload_bytes``: the smaller of the field's limit and the reader's."""
    wide = max_upload_bytes * REPORT_SIZE_FACTOR
    return UploadLimits(
        report=min(wide, MAX_REPORT_BYTES),
        series=min(wide, MAX_UPLOAD_BYTES),
        other=min(max_upload_bytes, MAX_UPLOAD_BYTES),
    )


def field_limit(field: str, max_upload_bytes: int = MAX_UPLOAD_BYTES) -> int:
    """The limit of the file an upload field is for (``FIELD_LIMITS``)."""
    return int(getattr(upload_limits(max_upload_bytes), FIELD_LIMITS[field]))


def megabytes(size: int, locale: str = "es") -> str:
    """Bytes as a reader says them: "5 MB", "7.3 MB" in English, "7,3 MB" in es and pt."""
    text = f"{size / 1_000_000:.1f}".rstrip("0").rstrip(".")
    return (text if locale == "en" else text.replace(".", ",")) + " MB"


def _words(locale: str) -> tuple[str, dict[str, str]]:
    lang = locale if locale in LIMIT_COPY else "es"
    return lang, LIMIT_COPY[lang]


def upload_limit_text(max_upload_bytes: int = MAX_UPLOAD_BYTES, locale: str = "es") -> str:
    """The limit of every field and what to do with a larger file, in ``locale``."""
    lang, words = _words(locale)
    limits = upload_limits(max_upload_bytes)
    sizes = {name: megabytes(getattr(limits, name), lang) for name in UploadLimits._fields}
    rest = words["merged"] if limits.series == limits.other else words["split"]
    return (words["lead"] + rest).format(**sizes) + words["shorten"]


def guide_limit_text(
    field: str, max_upload_bytes: int = MAX_UPLOAD_BYTES, locale: str = "es"
) -> str:
    """An export guide's line: the limit of the field its file goes in, then what to
    do with a larger file. No other format is suggested: the guide already names the
    file its platform exports."""
    lang, words = _words(locale)
    limit = megabytes(field_limit(field, max_upload_bytes), lang)
    return words["guide"].format(limit=limit) + words["shorten"]


__all__ = [
    "FIELD_LIMITS",
    "LIMIT_COPY",
    "UploadLimits",
    "field_limit",
    "guide_limit_text",
    "megabytes",
    "upload_limit_text",
    "upload_limits",
]
