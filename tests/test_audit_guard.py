"""The guard refuses our own profit language in both languages, never the client's."""

from __future__ import annotations

import pytest

from quant_trade.audit.guard import (
    AuditReportError,
    assert_report_clean,
    find_claims,
    scan_client_text,
)


@pytest.mark.parametrize(
    "text",
    [
        "esta estrategia es rentable",
        "ganancias garantizadas cada mes",
        "beneficios asegurados",
        "operar sin riesgo",
        "un sistema libre de riesgo",
        "hazte rico con esto",
        "dinero seguro",
        "el bot genera dinero mientras duermes",
        "vas a ganar el 20%",
        "te garantizamos resultados",
        "this strategy is profitable",
        "it makes money every week",
        "guaranteed returns",
        "resultados verificados por nuestro equipo",
        "robot certificado",
        "certificado de rentabilidad",
        "estrategia aprobada",
        "pasarás el reto",
        "superarás la evaluación",
        "vas a pasar la fase 1",
        "a verified track record",
        "certified strategy",
        "approved by our analysts",
        "you will pass the challenge",
        "you'll pass",
    ],
)
def test_claims_are_found(text: str) -> None:
    assert find_claims(text)
    with pytest.raises(AuditReportError):
        assert_report_clean("clean paragraph", text)


@pytest.mark.parametrize(
    "text",
    [
        "la rentabilidad anualizada observada fue del 12%",
        "el Sharpe es estadísticamente distinguible de cero",
        "no encontramos evidencia de sobreajuste con lo aportado",
        "the trades lose money net at the reference cost",
        "out of sample the Sharpe ratio is negative",
        "garantía de calidad de datos: sin duplicados",
        "DECLARED lo afirmó el cliente y no se pudo verificar",
        "Auditoría estadística de datos aportados – no verificados con el bróker – "
        "no garantiza resultados",
        "Statistical audit of supplied data – not verified with a broker – "
        "not a performance guarantee",
        "este informe no está certificado ni aprobado por ningún bróker",
        "this report is not certified",
    ],
)
def test_neutral_text_passes(text: str) -> None:
    assert find_claims(text) == []
    assert_report_clean(text)


def test_client_text_is_reported_not_refused() -> None:
    findings = scan_client_text("mi bot es rentable y makes money")
    assert {finding["pattern"] for finding in findings} == {
        r"\brentable\b",
        r"\bmakes? money\b",
    }
    assert all(finding["reason"].startswith("client_description") for finding in findings)
    assert scan_client_text("   ") == []


@pytest.mark.parametrize(
    "text",
    [
        "esta estratégia é lucrativa",
        "um robô rentável",
        "lucro garantido todo mês",
        "retornos assegurados",
        "operar sem risco",
        "um sistema livre de risco",
        "fique rico com isto",
        "dinheiro fácil",
        "o robô gera dinheiro enquanto você dorme",
        "você vai ganhar 20%",
        "você vai passar no desafio",
        "garantimos resultados",
        "estratégia aprovada",
        "passará na avaliação",
        "resultados verificados pela nossa equipe",
        "robô certificado",
    ],
)
def test_portuguese_claims_are_found(text: str) -> None:
    assert find_claims(text)
    with pytest.raises(AuditReportError):
        assert_report_clean("parágrafo limpo", text)


@pytest.mark.parametrize(
    "text",
    [
        "a rentabilidade anualizada observada foi de 12%",
        "não garante resultados futuros",
        "dados não verificados com a corretora",
        "um resultado passado não é garantido",
        "o Sharpe é estatisticamente distinguível de zero",
        "as operações perdem dinheiro líquido ao custo de referência",
    ],
)
def test_neutral_portuguese_passes(text: str) -> None:
    assert find_claims(text) == []
