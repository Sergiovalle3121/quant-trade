"""Every upload refusal has local guidance and bounded, anonymous dimensions."""

from __future__ import annotations

from html import unescape
from html.parser import HTMLParser

import pytest

from quant_trade.audit.guard import assert_report_clean
from quant_trade.audit.guides import GUIDES, GUIDES_PATH
from quant_trade.audit.i18n import spanish
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


def test_refusal_notes_have_central_spanish_rules() -> None:
    for category in REJECTION_CATEGORIES:
        for english, expected in zip(
            REJECTION_COPY["en"][category], REJECTION_COPY["es"][category], strict=True
        ):
            assert spanish(english) == expected


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
        ("bad_zip", "invalid_upload"),
    ),
)
def test_parser_codes_keep_distinct_causes(code: str, expected: str) -> None:
    assert classify(code) == expected


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
