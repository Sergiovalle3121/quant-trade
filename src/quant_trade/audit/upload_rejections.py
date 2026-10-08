"""Fixed, anonymous upload refusal categories and actionable customer guidance.

Only allow-listed tokens leave this module for operations counters. Neither
exception messages nor filenames are dimensions. Signature checks inspect at
most 4 KiB; an unknown prefix is not enough to refuse a text report, workbook
or PDF, whose tables may occur later in the file.
"""

from __future__ import annotations

import re
from html import escape

from quant_trade.audit.guides import GUIDES, GUIDES_PATH
from quant_trade.audit.importers import MT5_OPTIMIZATION_XML, REPORT_FORMATS

HEADER_BYTES = 4096
REJECTION_CATEGORIES: tuple[str, ...] = (
    "format_unknown",
    "image",
    "pdf_no_trades",
    "too_large",
    "too_few_rows",
    "dates_unreadable",
    "columns_missing",
    "files_mismatch",
    "rate_limited",
    "invalid_values",
    "invalid_declaration",
    "empty_file",
    "invalid_upload",
    "upload_timeout",
    "service_busy",
)
DETECTED_FORMATS = frozenset(
    {
        *REPORT_FORMATS,
        MT5_OPTIMIZATION_XML,
        "unknown",
        "csv",
        "image",
        "pdf",
        "html",
        "xml",
        "zip",
        "xlsx",
        "xls",
    }
)
REJECTION_DETECTORS = frozenset(
    {
        "admission",
        "upload",
        "detect_format",
        "import_report",
        "parse_equity",
        "parse_trades",
        "parse_returns",
        "declared",
        "importers",
        "schema",
        "mapping",
        "header",
        "body_limit",
        "rate_limit",
        "form",
    }
)

_CODES: dict[str, tuple[str, ...]] = {
    "format_unknown": (
        "unknown_format",
        "not_csv",
        "encoding",
        "legacy_xls",
        "opendocument_sheet",
        "bad_csv",
        "bad_xlsx",
        "bad_xml",
        "bad_zip",
        "zip_contents",
        "xml_doctype",
        "universal_not_a_table",
        "not_optimization",
        "optimization_file",
    ),
    "pdf_no_trades": ("pdf_statement",),
    "too_large": (
        "file_too_large",
        "xlsx_too_large",
        "flex_too_large",
        "line_too_long",
        "too_many_rows",
        "too_many_trades",
        "too_many_variants",
        "body_too_large",
    ),
    "too_few_rows": (
        "no_trades",
        "no_closed_trades",
        "flex_no_trades",
        "optimization_empty",
        "too_few_variants",
        "too_few_variant_rows",
        "mapped_curve_unreadable",
        "return_rows",
    ),
    "dates_unreadable": (
        "ambiguous_dates",
        "mixed_date_order",
        "ambiguous_date_order",
        "future_dates",
        "invalid_variant_timestamps",
        "variant_period_mismatch",
        "exits_before_entries",
        "grid_no_year",
        "grid_duplicate_year",
        "return_frequency_unknown",
    ),
    "columns_missing": (
        "missing_timestamp",
        "missing_value",
        "missing_trade_columns",
        "tradingview_columns",
        "universal_columns_missing",
        "universal_column_unreadable",
        "universal_unknown_column",
        "universal_column_twice",
        "universal_close_time_only",
        "pdf_columns",
        "ninjatrader_executions_symbol",
        "optimization_header",
        "return_columns",
        "equity_required",
    ),
    "files_mismatch": (
        "trades_and_report",
        "trade_list_as_curve",
        "optimization_mismatch",
    ),
    "invalid_values": (
        "value_too_large",
        "equity_not_positive",
        "balance_not_positive",
        "return_below_total_loss",
        "invalid_trade_cost",
        "mixed_trade_currencies",
        "variants_not_numeric",
        "ambiguous_decimal_mark",
        "mixed_decimal_marks",
        "mapped_results_below_zero",
        "return_compounding",
        "return_values",
        "return_unit_mixed",
    ),
    "invalid_declaration": (
        "bad_initial_balance",
        "invalid_declared",
        "return_frequency",
        "return_unit",
        "return_unit_mismatch",
        "return_frequency_mismatch",
    ),
    "empty_file": ("empty",),
}
_CATEGORY_BY_CODE = {code: category for category, codes in _CODES.items() for code in codes}


def safe_format(source_format: str | None) -> str:
    """A bounded operations dimension; unknown labels never reach storage."""
    return (
        source_format
        if source_format is not None and source_format in DETECTED_FORMATS
        else ("unknown")
    )


def safe_detector(detector: str | None) -> str:
    return detector if detector is not None and detector in REJECTION_DETECTORS else "admission"


def classify(code: str, *, detected_format: str = "unknown") -> str:
    """Classify a stable parser code without inspecting an exception's text."""
    if code in REJECTION_CATEGORIES:
        return code
    if detected_format == "image":
        return "image"
    return _CATEGORY_BY_CODE.get(code, "invalid_upload")


def header_format(head: bytes) -> str:
    """Identify a container from a bounded prefix, without parsing the upload.

    The CSV label identifies delimiters only, not a supported trade schema.
    PDFs still need the existing table reader; a PDF header proves no rows.
    """
    head = head[:HEADER_BYTES]
    if head.startswith(
        (
            b"\x89PNG\r\n\x1a\n",
            b"\xff\xd8\xff",
            b"GIF87a",
            b"GIF89a",
            b"II*\x00",
            b"MM\x00*",
            b"\x00\x00\x01\x00",
        )
    ):
        return "image"
    if len(head) >= 14 and head.startswith(b"BM") and head[6:10] == b"\x00" * 4:
        return "image"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image"
    if head[4:8] == b"ftyp" and head[8:12] in {b"avif", b"avis", b"heic", b"heix"}:
        return "image"
    stripped = head.lstrip()
    if stripped.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        return "zip"
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "xls"
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = head.decode("utf-16", errors="replace")
    else:
        text = head.decode("utf-8-sig", errors="replace")
    text = text.lstrip().lower()
    if re.match(r"(?:<\?xml[^>]*\?>\s*)?<svg(?:\s|>)", text):
        return "image"
    if text.startswith(("<!doctype html", "<html", "<table")):
        return "html"
    if text.startswith(("<?xml", "<workbook")):
        return "xml"
    first_line = text.split("\n", 1)[0]
    if any(delimiter in first_line for delimiter in (",", ";", "\t")):
        return "csv"
    return "unknown"


def header_rejection(head: bytes) -> str | None:
    """Refuse only definite unsupported signatures, never unknown text."""
    head = head[:HEADER_BYTES]
    if header_format(head) == "image":
        return "image"
    if head.startswith((b"\x7fELF", b"Rar!\x1a\x07", b"7z\xbc\xaf\x27\x1c", b"fLaC")):
        return "format_unknown"
    return None


# (What failed, concrete next step). No client-provided values are interpolated.
REJECTION_COPY: dict[str, dict[str, tuple[str, str]]] = {
    "es": {
        "format_unknown": (
            "No reconocimos un formato de informe compatible en este archivo.",
            "Exporta el historial de operaciones en CSV o Excel siguiendo la guía de "
            "CSV universal.",
        ),
        "image": (
            "El archivo es una imagen o captura, no una tabla de operaciones.",
            "En MT5, exporta el informe en HTML; en otra plataforma, exporta el historial en CSV "
            "o Excel. Usa las guías de abajo.",
        ),
        "pdf_no_trades": (
            "No se pudo leer una tabla de operaciones en este PDF.",
            "Descarga el historial original en CSV, Excel o HTML. Si es una captura o un PDF "
            "escaneado, exporta los datos desde la plataforma siguiendo su guía.",
        ),
        "too_large": (
            "El archivo supera un límite de tamaño, filas o columnas del lector.",
            "Exporta solo el historial del periodo que quieres revisar en CSV, sin imágenes ni "
            "hojas adicionales, y vuelve a subirlo.",
        ),
        "too_few_rows": (
            "No hay suficientes filas utilizables para leer este archivo.",
            "Exporta el historial completo con sus fechas y cifras; comprueba que haya al menos "
            "dos filas distintas de datos en la curva.",
        ),
        "dates_unreadable": (
            "Las fechas son ambiguas, inconsistentes o no se pueden usar.",
            "Revisa la columna de fecha y exporta con fechas AAAA-MM-DD, manteniendo la hora "
            "si corresponde, sin mezclar el orden de día y mes.",
        ),
        "columns_missing": (
            "Faltan columnas necesarias o no pudimos reconocer las que elegiste.",
            "Indica qué representa cada columna o exporta de nuevo siguiendo la guía de CSV "
            "universal, con las fechas, cantidades y precios de las operaciones.",
        ),
        "files_mismatch": (
            "Los archivos están mezclados, puestos en un campo equivocado o no corresponden "
            "entre sí.",
            "Pon el informe o la lista de operaciones exportada por tu plataforma en "
            "«Informe de tu plataforma» y deja vacío «Operaciones cerradas»: ese campo solo "
            "acompaña a una curva, nunca a un informe. «Curva de equity o serie de retornos» "
            "lleva fechas con saldos o retornos, no una lista de operaciones. En «Exportación "
            "de optimización de MT5» va el XML de ese mismo informe.",
        ),
        "rate_limited": (
            "Se alcanzó el límite de intentos de subida de esta hora.",
            "Espera una hora antes de volver a subir el archivo y revisa la guía de exportación.",
        ),
        "invalid_values": (
            "El archivo contiene cifras que el lector no puede usar de forma consistente.",
            "Revisa los separadores decimales, las unidades y la columna de saldo o resultado; "
            "vuelve a exportar los datos originales sin modificar las cifras.",
        ),
        "invalid_declaration": (
            "Una declaración del formulario tiene un valor no válido.",
            "Revisa los campos que completaste y corrige las cifras o fechas indicadas antes "
            "de volver a elegir el archivo.",
        ),
        "empty_file": (
            "El archivo llegó vacío, sin datos para leer.",
            "Abre la exportación, comprueba que incluya el historial y vuelve a elegir el "
            "archivo guardado, siguiendo la guía de tu plataforma.",
        ),
        "invalid_upload": (
            "No pudimos leer esta subida con los archivos y opciones indicados.",
            "Revisa el detalle del error y vuelve a exportar el historial original siguiendo "
            "la guía de tu plataforma.",
        ),
        "upload_timeout": (
            "La subida no terminó dentro del tiempo disponible.",
            "Comprueba tu conexión y vuelve a elegir el archivo; puedes exportar el historial "
            "en CSV para reducir su tamaño.",
        ),
        "service_busy": (
            "El servicio está ocupado y no pudo empezar a leer la subida.",
            "Espera unos minutos y vuelve a elegir el archivo para intentarlo de nuevo.",
        ),
    },
    "en": {
        "format_unknown": (
            "We did not recognise a supported report format in this file.",
            "Export the trade history as CSV or Excel following the universal CSV guide.",
        ),
        "image": (
            "The file is an image or screenshot, not a table of trades.",
            "In MT5, export the report as HTML; on another platform, export the history as CSV "
            "or Excel. Follow the guides below.",
        ),
        "pdf_no_trades": (
            "A table of trades could not be read from this PDF.",
            "Download the original history as CSV, Excel or HTML. For a screenshot or scanned "
            "PDF, export the data from the platform following its guide.",
        ),
        "too_large": (
            "The file exceeds a reader limit on size, rows or columns.",
            "Export only the history for the period you want to review as CSV, without images "
            "or extra sheets, and upload it again.",
        ),
        "too_few_rows": (
            "There are not enough usable rows to read this file.",
            "Export the complete history with dates and values; check that the curve contains "
            "at least two distinct data rows.",
        ),
        "dates_unreadable": (
            "The dates are ambiguous, inconsistent or unusable.",
            "Check the date column and export dates as YYYY-MM-DD, keeping the time where "
            "applicable, without mixing day and month order.",
        ),
        "columns_missing": (
            "Required columns are missing or we could not recognise the columns you chose.",
            "Name what each column represents or export again following the universal CSV "
            "guide, with the trade dates, quantities and prices.",
        ),
        "files_mismatch": (
            "The files are mixed, placed in the wrong field or do not belong together.",
            'Put the report or the trade list exported by your platform in "Your platform '
            'report" and leave "Closed trades" empty: that field only goes with a curve, '
            'never with a report. "Equity curve or return series" takes dates with balances '
            'or returns, not a trade list. "MT5 optimisation export" takes the XML of that '
            "same report.",
        ),
        "rate_limited": (
            "The upload attempt limit for this hour has been reached.",
            "Wait one hour before uploading again and check the export guide.",
        ),
        "invalid_values": (
            "The file contains numbers the reader cannot use consistently.",
            "Check decimal separators, units and the balance or result column; export the "
            "original data again without changing the numbers.",
        ),
        "invalid_declaration": (
            "A declaration in the form has an invalid value.",
            "Review the fields you filled in and correct the indicated numbers or dates "
            "before choosing the file again.",
        ),
        "empty_file": (
            "The file arrived empty, with no data to read.",
            "Open the export, check that it includes the history and select the saved file "
            "again, following your platform's guide.",
        ),
        "invalid_upload": (
            "We could not read this upload with the files and options supplied.",
            "Review the error detail and export the original history again following your "
            "platform's guide.",
        ),
        "upload_timeout": (
            "The upload did not finish within the available time.",
            "Check your connection and select the file again; exporting the history as CSV "
            "can reduce its size.",
        ),
        "service_busy": (
            "The service is busy and could not start reading the upload.",
            "Wait a few minutes and choose the file again to retry.",
        ),
    },
    "pt": {
        "format_unknown": (
            "Não reconhecemos um formato de relatório compatível neste arquivo.",
            "Exporte o histórico de operações em CSV ou Excel seguindo o guia de CSV universal.",
        ),
        "image": (
            "O arquivo é uma imagem ou captura de tela, não uma tabela de operações.",
            "No MT5, exporte o relatório em HTML; em outra plataforma, exporte o histórico em "
            "CSV ou Excel. Siga os guias abaixo.",
        ),
        "pdf_no_trades": (
            "Não foi possível ler uma tabela de operações neste PDF.",
            "Baixe o histórico original em CSV, Excel ou HTML. Se for uma captura ou um PDF "
            "digitalizado, exporte os dados da plataforma seguindo o guia correspondente.",
        ),
        "too_large": (
            "O arquivo ultrapassa um limite de tamanho, linhas ou colunas do leitor.",
            "Exporte apenas o histórico do período que deseja revisar em CSV, sem imagens nem "
            "planilhas adicionais, e envie novamente.",
        ),
        "too_few_rows": (
            "Não há linhas utilizáveis suficientes para ler este arquivo.",
            "Exporte o histórico completo com datas e valores; confira se a curva contém "
            "pelo menos duas linhas distintas de dados.",
        ),
        "dates_unreadable": (
            "As datas são ambíguas, inconsistentes ou não podem ser utilizadas.",
            "Confira a coluna de data e exporte as datas como AAAA-MM-DD, mantendo o horário "
            "quando aplicável, sem misturar a ordem de dia e mês.",
        ),
        "columns_missing": (
            "Faltam colunas necessárias ou não reconhecemos as colunas que você escolheu.",
            "Indique o que cada coluna representa ou exporte novamente seguindo o guia de "
            "CSV universal, com as datas, quantidades e preços das operações.",
        ),
        "files_mismatch": (
            "Os arquivos estão misturados, colocados no campo errado ou não correspondem entre si.",
            "Coloque o relatório ou a lista de operações exportada pela plataforma em "
            '"Relatório da sua plataforma" e deixe vazio "Operações fechadas": esse campo só '
            'acompanha uma curva, nunca um relatório. "Curva de equity ou série de retornos" '
            "recebe datas com saldos ou retornos, não uma lista de operações. "
            '"Exportação de otimização do MT5" recebe o XML desse mesmo relatório.',
        ),
        "rate_limited": (
            "O limite de tentativas de envio desta hora foi atingido.",
            "Espere uma hora antes de enviar novamente e confira o guia de exportação.",
        ),
        "invalid_values": (
            "O arquivo contém números que o leitor não pode utilizar de forma consistente.",
            "Confira os separadores decimais, as unidades e a coluna de saldo ou resultado; "
            "exporte novamente os dados originais sem alterar os números.",
        ),
        "invalid_declaration": (
            "Uma declaração no formulário tem um valor inválido.",
            "Revise os campos preenchidos e corrija os números ou datas indicados antes de "
            "escolher o arquivo novamente.",
        ),
        "empty_file": (
            "O arquivo chegou vazio, sem dados para ler.",
            "Abra a exportação, confira se ela inclui o histórico e selecione novamente o "
            "arquivo salvo, seguindo o guia da sua plataforma.",
        ),
        "invalid_upload": (
            "Não conseguimos ler este envio com os arquivos e opções informados.",
            "Confira o detalhe do erro e exporte novamente o histórico original seguindo o "
            "guia da sua plataforma.",
        ),
        "upload_timeout": (
            "O envio não terminou dentro do tempo disponível.",
            "Confira sua conexão e selecione o arquivo novamente; exportar o histórico em "
            "CSV pode reduzir o tamanho.",
        ),
        "service_busy": (
            "O serviço está ocupado e não conseguiu começar a ler o envio.",
            "Espere alguns minutos e escolha o arquivo novamente para tentar outra vez.",
        ),
    },
}

_LABELS = {
    "es": (
        "Formato detectado",
        "no reconocido",
        "Formatos aceptados",
        "Siguiente paso",
        "CSV o Excel de operaciones",
        "imagen",
    ),
    "en": (
        "Detected format",
        "not recognised",
        "Accepted formats",
        "Next step",
        "Trade CSV or Excel",
        "image",
    ),
    "pt": (
        "Formato detectado",
        "não reconhecido",
        "Formatos aceitos",
        "Próximo passo",
        "CSV ou Excel de operações",
        "imagem",
    ),
}
_FORMAT_NAMES: dict[str, str] = {
    "mt5_tester_html": "MT5 HTML",
    "mt5_history_html": "MT5 HTML",
    "mt5_tester_xlsx": "MT5 Excel",
    "mt5_history_xlsx": "MT5 Excel",
    "mt4_tester_html": "MT4 HTML",
    "mt4_statement_html": "MT4 HTML",
    "mt5_optimization_xml": "MT5 XML",
    "tradingview_csv": "TradingView CSV",
    "tradingview_xlsx": "TradingView Excel",
    "ninjatrader_csv": "NinjaTrader CSV",
    "ninjatrader_executions_csv": "NinjaTrader CSV",
    "quantconnect_trades_csv": "QuantConnect CSV",
    "backtestingpy_csv": "backtesting.py CSV",
    "vectorbt_csv": "vectorbt CSV",
    "myfxbook_csv": "Myfxbook CSV",
    "mql5_signal_csv": "MQL5 CSV",
    "fxblue_csv": "FX Blue CSV",
    "robinhood_csv": "Robinhood CSV",
    "universal_trades_csv": "CSV",
    "universal_fills_csv": "CSV",
    "csv": "CSV",
    "pdf": "PDF",
    "html": "HTML",
    "xml": "XML",
    "zip": "ZIP",
    "xlsx": "Excel",
    "xls": "Excel",
}


def rejection_guidance(
    category: str,
    detected_format: str | None = None,
    locale: str = "es",
    *,
    file_inspected: bool = True,
) -> str:
    """Fixed cause and export links, with a format only when a file was inspected."""
    locale = locale if locale in REJECTION_COPY else "es"
    category = classify(category)
    reason, next_step = REJECTION_COPY[locale][category]
    detected, unknown, accepted, step, universal_label, image_label = _LABELS[locale]
    source_format = safe_format(detected_format)
    format_name = (
        image_label if source_format == "image" else _FORMAT_NAMES.get(source_format, unknown)
    )
    format_line = f"<p>{escape(detected)}: {escape(format_name)}.</p>" if file_inspected else ""
    links: list[str] = []
    for slug, label in (
        ("mt5", "MT5 HTML"),
        ("mt4", "MT4 HTML"),
        ("tradingview", "TradingView CSV / Excel"),
        ("csv-universal", universal_label),
    ):
        guide = next(guide for guide in GUIDES if guide.slug == slug)
        path = f"{GUIDES_PATH[locale]}/{guide.slug_for(locale)}"
        links.append(f'<a href="{escape(path, quote=True)}">{escape(label)}</a>')
    return (
        f'<div class="upload-guidance" data-upload-rejection="{category}">'
        f"<p>{escape(reason)}</p>{format_line}"
        f"<p>{escape(accepted)}: {' · '.join(links)}.</p>"
        f"<p><strong>{escape(step)}:</strong> {escape(next_step)}</p></div>"
    )
