"""The continuous track record's words: equal keys in es, en and pt, the
guard in every language, the forbidden words, and every template rendered
with extreme figures."""

from __future__ import annotations

import inspect
import re
import string

import pytest

from quant_trade.audit import track_seal_copy, track_seal_pages
from quant_trade.audit.guard import find_claims
from quant_trade.audit.seo import BRAND
from quant_trade.audit.track_seal_copy import (
    ALLOWED_PHRASES,
    COPY,
    FORBIDDEN_WORDS,
    LANGUAGES,
    PATHS,
    all_texts,
)

EXTREME: dict[str, tuple[object, ...]] = {
    "n": (0, 1, 99_999),
    "m": (30, 99_999),
    "months": (0, 1, 99_999),
    "pace": ("0.0", "1.5", "99999.9"),
    "date": ("2026-01-01", "2099-12-31"),
    "start": ("2026-01-01",),
    "end": ("2026-12-31",),
    "days": (0, 1, 99_999),
    "opened": (0, 5),
    "allowed": (5,),
    "id": ("a" * 32,),
    "cls": ("A", "D", "—"),
}


def _fields(text: str) -> list[str]:
    return [name for _, name, _, _ in string.Formatter().parse(text) if name]


def _rendered() -> list[str]:
    """Every template rendered with each extreme value of its fields."""
    found: list[str] = []
    for text in all_texts():
        names = _fields(text)
        if not names:
            found.append(text)
            continue
        for name in names:
            assert name in EXTREME, f"unknown placeholder {name!r} in {text!r}"
        longest = max(len(EXTREME[name]) for name in names)
        for i in range(longest):
            values = {name: EXTREME[name][i % len(EXTREME[name])] for name in names}
            found.append(text.format(**values))
    return found


def test_the_three_languages_share_every_key() -> None:
    assert tuple(COPY) == LANGUAGES == ("es", "en", "pt")
    keys = {lang: set(copy) for lang, copy in COPY.items()}
    assert keys["es"] == keys["en"] == keys["pt"]
    assert set(PATHS) == set(LANGUAGES)
    assert {tuple(sorted(paths)) for paths in PATHS.values()} == {
        ("coherence", "example", "public", "records")
    }
    for lang, copy in COPY.items():
        for key, text in copy.items():
            assert text.strip(), (lang, key)


def test_every_sentence_passes_the_guard_with_extreme_figures() -> None:
    for text in _rendered():
        assert find_claims(text) == [], text
    for text in track_seal_pages.PANEL_TEXT.values():
        assert find_claims(text) == [], text


def test_no_forbidden_word_reaches_a_screen() -> None:
    for lang, words in FORBIDDEN_WORDS.items():
        for text in [*COPY[lang].values(), *_rendered()]:
            lowered = text.lower()
            for phrase in ALLOWED_PHRASES:
                lowered = lowered.replace(phrase, " ")
            for word in words:
                assert not re.search(rf"(?<!\w){re.escape(word)}(?!\w)", lowered), (
                    lang,
                    word,
                    text,
                )
    for text in track_seal_pages.PANEL_TEXT.values():
        for word in FORBIDDEN_WORDS["es"]:
            assert not re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text.lower()), (word, text)


def test_the_fixed_sentences_are_verbatim_in_spanish() -> None:
    es = COPY["es"]
    assert es["holder_checkbox"] == (
        "Soy titular de esta cuenta de trading o tengo su permiso para publicar este historial"
    )
    assert es["public_since"] == "público desde el {date} ({days} días después de abrirse)"
    assert es["calibration_caveat"] == "cambios aún no calibrados con re-exportaciones reales"
    assert es["in_progress"] == "en curso"
    assert es["class_full_note"] == "incluye lo anterior a la apertura, que no está cubierto"
    assert es["account_records"] == (
        f"Historiales abiertos por esta cuenta: {{n}}. {BRAND} no ve otras cuentas de la "
        "misma persona."
    )
    assert es["paid_note"] == "pagado por quien sube el archivo; pagar no cambia la clase"
    assert es["withdrawn"] == "retirado por quien lo abrió el {date}"
    assert es["other_record"] == f"¿Te pasaron otro historial? Revísalo en {BRAND}"
    assert es["example_banner"] == "Ejemplo con datos inventados; no es el historial de nadie"
    assert es["class_pending"] == "aún sin clase: {n} de {m} observaciones"
    assert es["time_to_know"] == "Tiempo para saber"
    assert es["ttk_no_mean"] == "no hay promedio positivo que medir"
    assert es["fresh_current"] == "Al día"
    assert es["fresh_stale"] == "sin cargas desde {date}"
    assert es["mismatch_line"] == (
        "Esta carga no coincide con la anterior en {n} operaciones; puede ser un ajuste del "
        "bróker o una edición."
    )
    assert es["refusal_already_recorded"] == "este archivo ya está registrado"
    assert es["refusal_account_differs"] == "no coincide con la cuenta del historial"
    assert es["coh_method"] == (
        "El método es público: detecta ediciones descuidadas, no a quien lo estudie."
    )
    assert es["coh_none"] == (
        "No encontramos las huellas que revisamos; eso no prueba que el archivo sea original."
    )


def test_every_refusal_code_has_a_sentence_in_every_language() -> None:
    from quant_trade.audit.track_seal_service import REFUSAL_CODES

    for lang in LANGUAGES:
        for code in REFUSAL_CODES:
            assert f"refusal_{code}" in COPY[lang], (lang, code)
        for kind in ("opened", "uploaded", "mismatch", "ended", "published", "unpublished"):
            assert f"event_{kind}" in COPY[lang], (lang, kind)


def test_the_brand_comes_only_from_seo() -> None:
    for module in (track_seal_copy, track_seal_pages):
        source = inspect.getsource(module)
        assert BRAND not in source.replace("BRAND", ""), module.__name__
    for text in all_texts():
        if BRAND in text:
            assert find_claims(text) == []


@pytest.mark.parametrize("lang", LANGUAGES)
def test_paths_are_private_shapes(lang: str) -> None:
    paths = PATHS[lang]
    assert paths["example"].startswith(paths["public"] + "/")
    assert paths["records"].startswith("/pt/" if lang == "pt" else "/")
    for value in paths.values():
        assert value.startswith("/") and not value.endswith("/")
