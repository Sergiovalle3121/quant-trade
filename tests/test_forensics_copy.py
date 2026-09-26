"""The words of the "Coherencia del archivo" page: same keys in every
language, every sentence past the guard, no forbidden word."""

from __future__ import annotations

import re
import string

import pytest

from quant_trade.audit.forensics import copy as words
from quant_trade.audit.forensics.families import FAMILIES
from quant_trade.audit.forensics.results import EVIDENCE, STATUSES
from quant_trade.audit.forensics.review import CHECK_ORDER, REASONS
from quant_trade.audit.guard import assert_report_clean, find_claims

#: Words that must never describe a file or a record on this page (with
#: their English and Portuguese twins), matched on word boundaries.
FORBIDDEN = (
    "limpio",
    "limpia",
    "auténtico",
    "auténtica",
    "genuino",
    "genuina",
    "verificado",
    "verificada",
    "falso",
    "falsa",
    "manipulado",
    "manipulada",
    "inalterable",
    "sello",
    "para siempre",
    "demuestra",
    "archivo real",
    "historial real",
    "es real",
    "clean",
    "authentic",
    "genuine",
    "verified",
    "fake",
    "manipulated",
    "unalterable",
    "seal",
    "forever",
    "proves the file is real",
    "real file",
    "limpo",
    "limpa",
    "autêntico",
    "autêntica",
    "genuíno",
    "genuína",
    "falso",
    "falsa",
    "manipulado",
    "manipulada",
    "inalterável",
    "selo",
    "para sempre",
    "demonstra",
    "arquivo real",
    "histórico real",
    "detén",
    "pausa",
    "copia",
    "invierte",
    "compra",
    "vende",
)

_EXTREMES = (
    {"n_hits": "0", "n_rows": "0", "rows": "0", "n": "0"},
    {"n_hits": "1", "n_rows": "1", "rows": "3", "n": "1"},
    {"n_hits": "99999", "n_rows": "99999", "rows": "3, 7, 12, 40, 99999", "n": "19"},
)
_FILL = {
    "unexplained": "0",
    "cp95": "100.0",
    "signal": "0",
    "info": "1",
    "clean": "2",
    "not_measured": "3",
    "reason": "x",
}


def _placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


def _filled(template: str, values: dict[str, str]) -> str:
    return template.format(**{**_FILL, **values})


def test_every_table_has_the_same_keys_in_every_language() -> None:
    for name, table in words.TABLES.items():
        assert set(table) == set(words.LOCALES), name
        keys = set(table["es"])
        for locale in words.LOCALES:
            assert set(table[locale]) == keys, (name, locale)
            assert all(isinstance(value, str) and value for value in table[locale].values()), name


def test_the_tables_cover_the_battery_closed_lists() -> None:
    for locale in words.LOCALES:
        assert set(words.CHECK_NAMES[locale]) == set(CHECK_ORDER)
        assert set(words.CHECK_FACTS[locale]) == set(CHECK_ORDER)
        assert set(words.REASON_TEXT[locale]) == set(REASONS)
        assert set(words.STATUS_WORDS[locale]) == set(STATUSES)
        assert set(words.EVIDENCE_WORDS[locale]) == set(EVIDENCE)
        assert set(words.EVIDENCE_HELP[locale]) == set(EVIDENCE)
        assert set(words.FAMILY_NAMES[locale]) == set(FAMILIES)


def test_templates_use_the_same_placeholders_in_every_language() -> None:
    for name, table in words.TABLES.items():
        for key, spanish in table["es"].items():
            for locale in ("en", "pt"):
                assert _placeholders(table[locale][key]) == _placeholders(spanish), (name, key)


@pytest.mark.parametrize("locale", words.LOCALES)
def test_every_fixed_sentence_passes_the_guard(locale: str) -> None:
    for text in words.fixed_sentences(locale):
        for values in _EXTREMES:
            filled = _filled(text, values)
            assert_report_clean(filled)
            assert find_claims(filled) == [], filled
            assert "{" not in filled and "}" not in filled, filled


@pytest.mark.parametrize("locale", words.LOCALES)
def test_no_forbidden_word_describes_the_file(locale: str) -> None:
    for text in words.fixed_sentences(locale):
        lowered = _filled(text, _EXTREMES[1]).lower()
        for word in FORBIDDEN:
            assert re.search(rf"\b{re.escape(word)}\b", lowered) is None, (word, text)


def test_the_required_sentences_are_present_verbatim() -> None:
    es, en, pt = (words.COPY[locale] for locale in words.LOCALES)
    assert es["method"] == (
        "El método es público: detecta ediciones descuidadas, no a quien lo estudie."
    )
    assert es["no_findings"] == (
        "No encontramos las huellas que revisamos; eso no prueba que el archivo sea original."
    )
    assert es["legit"] == (
        "Puede tener explicaciones legítimas; conviene aclararlo con quien generó el archivo."
    )
    assert en["legit"] == (
        "It may have legitimate explanations; it is worth clarifying with whoever generated "
        "the file."
    )
    assert es["title"] == "Coherencia del archivo"
    assert en["title"] == "File consistency"
    assert pt["title"] == "Coerência do arquivo"
    assert "limpio" not in es["limits"].lower()
    for locale in words.LOCALES:
        # The status chips never say "clean" in any language.
        assert words.STATUS_WORDS[locale]["CLEAN"].lower() not in ("limpio", "clean", "limpo")
        assert "archivo editado con cuidado" in words.COPY["es"]["limits"]


def test_figure_labels_fall_back_to_the_base_key_and_then_the_code() -> None:
    assert words.figure_label("n_hits", "es") == "hallazgos"
    assert words.figure_label("declared_2", "en") == "declared value"
    assert words.figure_label("net_profit_gross_left", "pt").startswith("líquido = ")
    assert words.figure_label("net_profit_gross_left", "pt").endswith("(lado esquerdo)")
    assert words.figure_label("cumulative_examined", "en") == "cumulative (examined)"
    assert words.figure_label("something_new", "es") == "something new"
    assert words.figure_label("something_new_3", "es") == "something new"


def test_brand_appears_only_through_the_seo_constant() -> None:
    import inspect

    from quant_trade.audit.seo import BRAND

    source = inspect.getsource(words)
    assert f'"{BRAND}' not in source and f" {BRAND} " not in source.replace("{BRAND}", "")
    assert BRAND in words.COPY["es"]["no_change"]
