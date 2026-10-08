"""Every upload refusal has local guidance and bounded, anonymous dimensions."""

from __future__ import annotations

import ast
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

import pytest

from quant_trade import audit
from quant_trade.audit.guard import assert_report_clean, find_claims
from quant_trade.audit.guides import GUIDES, GUIDES_PATH
from quant_trade.audit.i18n import spanish
from quant_trade.audit.schema import ParseError, parse_equity_csv
from quant_trade.audit.upload_rejections import (
    DETECTED_FORMATS,
    HEADER_BYTES,
    REJECTION_CATEGORIES,
    REJECTION_COPY,
    REJECTION_DETECTORS,
    classify,
    header_format,
    header_rejection,
    rejection_guidance,
    safe_detector,
    safe_format,
)


class _Links(HTMLParser):
    def __init__(self, text: str) -> None:
        super().__init__()
        self.hrefs: list[str] = []
        self.feed(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self.hrefs.extend(value for name, value in attrs if name == "href" and value)


@pytest.mark.parametrize("locale", ("es", "en", "pt"))
@pytest.mark.parametrize("category", REJECTION_CATEGORIES)
def test_each_refusal_explains_cause_next_step_and_real_guides(category: str, locale: str) -> None:
    page = rejection_guidance(category, "unknown", locale)
    reason, next_step = REJECTION_COPY[locale][category]
    assert reason in unescape(page)
    assert next_step in unescape(page)
    paths = {f"{GUIDES_PATH[locale]}/{guide.slug_for(locale)}" for guide in GUIDES}
    links = _Links(page).hrefs
    assert 2 <= len(links) <= 5
    assert all(link in paths for link in links)
    assert_report_clean(page)


@pytest.mark.parametrize("locale", ("es", "en", "pt"))
@pytest.mark.parametrize("source_format", sorted(DETECTED_FORMATS))
def test_each_detected_format_is_guard_safe(source_format: str, locale: str) -> None:
    assert_report_clean(rejection_guidance("invalid_upload", source_format, locale))


@pytest.mark.parametrize("category", REJECTION_CATEGORIES)
def test_refusal_notes_are_distinct_in_each_language_and_guard_safe(category: str) -> None:
    translations = [REJECTION_COPY[locale][category] for locale in ("es", "en", "pt")]
    for notes in zip(*translations, strict=True):
        assert len(set(notes)) == 3
        assert all(find_claims(note) == [] for note in notes)


@pytest.mark.parametrize("category", REJECTION_CATEGORIES)
def test_spanish_rules_stay_in_sync_with_refusal_notes(category: str) -> None:
    for english, expected in zip(
        REJECTION_COPY["en"][category], REJECTION_COPY["es"][category], strict=True
    ):
        assert spanish(english) == expected


def _parser_codes(tree: ast.Module, module_name: str) -> set[str]:
    """Read constructors, the factsheet wrapper and return-series copy keys."""
    codes: set[str] = set()
    forwarded_calls = {
        child
        for node in tree.body
        if module_name == "factsheet.py"
        and isinstance(node, ast.FunctionDef)
        and node.name == "_no_grid"
        for child in ast.walk(node)
        if isinstance(child, ast.Call)
    }

    def add_code(node: ast.AST) -> None:
        if isinstance(node, ast.IfExp):
            add_code(node.body)
            add_code(node.orelse)
        else:
            assert isinstance(node, ast.Constant) and isinstance(node.value, str), (
                module_name,
                ast.unparse(node),
            )
            codes.add(node.value)

    for node in ast.walk(tree):
        if module_name == "return_series.py" and isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id == "ERRORS" for target in targets):
                assert isinstance(node.value, ast.Dict)
                for key in node.value.keys:
                    assert key is not None
                    add_code(key)
        if not isinstance(node, ast.Call):
            continue
        name = (
            node.func.id
            if isinstance(node.func, ast.Name)
            else node.func.attr
            if isinstance(node.func, ast.Attribute)
            else ""
        )
        if name not in {"ParseError", "ReportFormatError", "ReturnSeriesError", "_no_grid"}:
            continue
        code = next((keyword.value for keyword in node.keywords if keyword.arg == "code"), None)
        if code is None and name in {"ReportFormatError", "ReturnSeriesError"}:
            code = node.args[0]
        elif code is None and name == "_no_grid":
            code = node.args[2]
        if code is None:
            code = ast.Constant(value="parse")  # ParseError's implicit default is a code too.
        if node in forwarded_calls and ast.unparse(code) == "code":
            continue  # _no_grid forwards its third argument; its callers are scanned above.
        if module_name == "schema.py" and ast.unparse(code) == "exc.code":
            continue  # The live-statement wrapper preserves an already classified error.
        add_code(code)
    return codes


def test_every_parser_error_code_has_specific_guidance() -> None:
    """New codes anywhere in the package must not silently use generic guidance."""
    assert audit.__file__ is not None
    # No current parser code needs the generic fallback. Exceptions must be listed here.
    accepted_generic_codes: frozenset[str] = frozenset()
    codes: set[str] = set()
    for path in sorted(Path(audit.__file__).parent.rglob("*.py")):
        module_codes = _parser_codes(ast.parse(path.read_text(encoding="utf-8")), path.name)
        unmapped = {code for code in module_codes if classify(code) == "invalid_upload"}
        assert unmapped <= accepted_generic_codes, (path.name, sorted(unmapped))
        codes.update(module_codes)
    assert codes


@pytest.mark.parametrize(
    ("module_name", "source", "expected_code"),
    (
        ("new_reader.py", 'imp.ReportFormatError("new_code", "message", "mensaje")', "new_code"),
        ("factsheet.py", '_no_grid("message", "mensaje", "new_code")', "new_code"),
        ("return_series.py", 'ERRORS: dict = {"new_code": {"en": "message"}}', "new_code"),
        (
            "new_reader.py",
            'ParseError("message", code="new_code" if flag else "empty")',
            "new_code",
        ),
        ("new_reader.py", 'ReturnSeriesError("x")', "x"),
        ("new_reader.py", 'ParseError("message")', "parse"),
    ),
)
def test_parser_inventory_detects_unmapped_codes_in_all_supported_forms(
    module_name: str, source: str, expected_code: str
) -> None:
    codes = _parser_codes(ast.parse(source), module_name)
    assert expected_code in codes
    assert {code for code in codes if classify(code) == "invalid_upload"} == {expected_code}


@pytest.mark.parametrize(
    ("locale", "detected_label"),
    (("es", "Formato detectado:"), ("en", "Detected format:"), ("pt", "Formato detectado:")),
)
@pytest.mark.parametrize(
    "category",
    (
        "rate_limited",
        "invalid_declaration",
        "service_busy",
        "upload_timeout",
        "too_large",
        "empty_file",
    ),
)
def test_uninspected_upload_does_not_claim_a_detected_format(
    category: str, locale: str, detected_label: str
) -> None:
    page = rejection_guidance(category, "unknown", locale, file_inspected=False)
    assert detected_label not in unescape(page)
    assert REJECTION_COPY[locale][category][1] in unescape(page)
    assert find_claims(page) == []
    assert detected_label in unescape(rejection_guidance(category, "unknown", locale))


@pytest.mark.parametrize("value", ("alice@example.test", "private.pdf", "203.0.113.1", "<script>"))
def test_dimensions_and_guidance_never_echo_unknown_input(value: str) -> None:
    assert safe_format(value) == "unknown"
    assert safe_detector(value) == "admission"
    assert classify(value) == "invalid_upload"
    assert value not in rejection_guidance(value, value)


def test_allowlisted_values_survive_normalization() -> None:
    assert all(safe_format(value) == value for value in DETECTED_FORMATS)
    assert all(safe_detector(value) == value for value in REJECTION_DETECTORS)
    assert all(classify(value) == value for value in REJECTION_CATEGORIES)


@pytest.mark.parametrize(
    ("code", "expected"),
    (
        ("unknown_format", "format_unknown"),
        ("pdf_statement", "pdf_no_trades"),
        ("file_too_large", "too_large"),
        ("too_many_rows", "too_large"),
        ("no_closed_trades", "too_few_rows"),
        ("ambiguous_dates", "dates_unreadable"),
        ("mixed_date_order", "dates_unreadable"),
        ("grid_no_year", "dates_unreadable"),
        ("missing_timestamp", "columns_missing"),
        ("universal_unknown_column", "columns_missing"),
        ("pdf_columns", "columns_missing"),
        ("value_too_large", "invalid_values"),
        ("bad_initial_balance", "invalid_declaration"),
        ("return_unit_mismatch", "invalid_declaration"),
        ("return_rows", "too_few_rows"),
        ("return_columns", "columns_missing"),
        ("empty", "empty_file"),
        ("bad_csv", "format_unknown"),
        ("bad_xlsx", "format_unknown"),
        ("bad_xml", "format_unknown"),
        ("bad_zip", "format_unknown"),
        ("zip_contents", "format_unknown"),
        ("xml_doctype", "format_unknown"),
        ("universal_not_a_table", "format_unknown"),
        ("not_optimization", "format_unknown"),
        ("optimization_file", "format_unknown"),
        ("trades_and_report", "files_mismatch"),
        ("trade_list_as_curve", "files_mismatch"),
        ("optimization_mismatch", "files_mismatch"),
        ("equity_required", "columns_missing"),
    ),
)
def test_parser_codes_keep_distinct_causes(code: str, expected: str) -> None:
    assert classify(code) == expected


@pytest.mark.parametrize(
    ("locale", "report_field"),
    (
        ("es", "Informe de tu plataforma"),
        ("en", "Your platform report"),
        ("pt", "Relatório da sua plataforma"),
    ),
)
def test_trade_list_detail_and_guidance_point_to_the_same_supported_field(
    locale: str, report_field: str
) -> None:
    payload = b"entry_time,exit_time,quantity,entry_price,exit_price,side\n"
    payload += b"2024-01-01,2024-01-02,1,100,101,long\n"
    with pytest.raises(ParseError) as caught:
        parse_equity_csv(payload)
    assert caught.value.code == "trade_list_as_curve"
    assert report_field in caught.value.localized(locale)
    assert report_field in REJECTION_COPY[locale]["files_mismatch"][1]
    assert find_claims(caught.value.localized(locale)) == []


@pytest.mark.parametrize(
    ("locale", "fields", "not_both"),
    (
        (
            "es",
            (
                "Informe de tu plataforma",
                "Operaciones cerradas",
                "Curva de equity o serie de retornos",
                "Exportación de optimización de MT5",
            ),
            "no ambos",
        ),
        (
            "en",
            (
                "Your platform report",
                "Closed trades",
                "Equity curve or return series",
                "MT5 optimisation export",
            ),
            "not both",
        ),
        (
            "pt",
            (
                "Relatório da sua plataforma",
                "Operações fechadas",
                "Curva de equity ou série de retornos",
                "Exportação de otimização do MT5",
            ),
            "não os dois",
        ),
    ),
)
def test_mismatch_next_step_names_a_field_for_each_file_without_repeating_the_alert(
    locale: str, fields: tuple[str, ...], not_both: str
) -> None:
    from audit_fixtures import csv_bytes, synthetic_mt5_report, trades_frame

    from quant_trade.audit.pages import upload_page
    from quant_trade.audit.schema import DeclaredMetadata, build_inputs

    next_step = REJECTION_COPY[locale]["files_mismatch"][1]
    form = unescape(upload_page(locale=locale))
    for field in fields:
        # The same label the customer reads on the upload form.
        assert field in next_step
        assert field in form
    with pytest.raises(ParseError) as caught:
        build_inputs(
            None,
            DeclaredMetadata(),
            report_bytes=synthetic_mt5_report(days=3),
            trades_bytes=csv_bytes(trades_frame(3)),
        )
    assert caught.value.code == "trades_and_report"
    alert = caught.value.localized(locale)
    # The alert already says "not both"; the next step says where each file goes.
    assert not_both in alert
    assert not_both not in next_step
    assert alert not in next_step
    assert find_claims(next_step) == []


@pytest.mark.parametrize(
    "prefix",
    (
        b"\x89PNG\r\n\x1a\n",
        b"\xff\xd8\xff",
        b"GIF89a",
        b"GIF87a",
        b"BM\x00\x00\x00\x00\x00\x00\x00\x00\x36\x00\x00\x00",
        b"II*\x00",
        b"MM\x00*",
        b"\x00\x00\x01\x00",
        b"RIFF1234WEBP",
        b"\x00\x00\x00\x20ftypavif",
        b"<svg xmlns='http://www.w3.org/2000/svg'>",
    ),
)
def test_images_are_refused_from_signature(prefix: bytes) -> None:
    assert header_format(prefix) == "image"
    assert header_rejection(prefix) == "image"


@pytest.mark.parametrize("prefix", (b"\x7fELF", b"Rar!\x1a\x07", b"7z\xbc\xaf\x27\x1c", b"fLaC"))
def test_definite_unsupported_signatures_refuse_without_reading_rows(prefix: bytes) -> None:
    assert header_rejection(prefix) == "format_unknown"


@pytest.mark.parametrize(
    ("prefix", "expected"),
    (
        (b"%PDF-1.7", "pdf"),
        (b"PK\x03\x04", "zip"),
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "xls"),
        (b"<html>", "html"),
        ("<html>".encode("utf-16"), "html"),
        (b"<?xml version='1.0'?>", "xml"),
        (b"<?xml version='1.0'?><Workbook><Cell><svg>illustration</svg>", "xml"),
        (b"timestamp,equity\n", "csv"),
        (b"BM,quantity,price\n", "csv"),
        (b"Report title\n", "unknown"),
        (b"\x1f\x8b", "unknown"),
        (b"", "unknown"),
    ),
)
def test_accepted_or_inconclusive_headers_still_reach_existing_readers(
    prefix: bytes, expected: str
) -> None:
    assert header_format(prefix) == expected
    assert header_rejection(prefix) is None


def test_signature_sniff_is_bounded_and_cannot_find_later_images() -> None:
    class PrefixOnly(bytes):
        def __getitem__(self, key: int | slice) -> bytes:
            assert isinstance(key, slice) and key.start is None and key.stop == HEADER_BYTES
            return bytes(super().__getitem__(key))

    prefix = PrefixOnly(b"Report title\n".ljust(HEADER_BYTES, b" ") + b"<svg>" * 1000)
    assert header_format(prefix) == "unknown"
    assert header_rejection(prefix) is None
