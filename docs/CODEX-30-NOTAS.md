# Codex 30 · Enlaces de la audiencia de retos

Fecha: 2026-10-11. Rama: `fix/retos-enlaces-guias`.
Base revisada: `origin/main` en `d37e500`.

## Cambios

- Entradas propias para Tradovate, TopstepX y Sierra Chart en español, inglés y
  portugués, con enlaces a sus guías. Los formatos siguen lo descrito en ellas:
  CSV de Account Reports, archivo de Trades y texto con tabuladores, respectivamente.
- El texto del importador universal queda sin enumerar plataformas. La página de
  retos deja de mencionar Rithmic y cTrader; la guía de cTrader no está en la base
  revisada, por lo que no se enlaza.
- Se conserva un enlace a la calculadora de reto y otro a la tabla de reglas,
  que ya existían. Se añade la calculadora de ruina con una frase fáctica sobre
  estimaciones a partir de cifras declaradas en los tres idiomas.
- Se mantiene «alcanzar el objetivo». No cambia ningún cálculo ni criterio de riesgo.

## Validación

Intérprete: `D:\wt\.venv-pp\Scripts\python.exe`.
`PYTHONPATH=D:\wt\codex-30\src`.
Los directorios temporales de pytest siguen el prefijo solicitado
`C:\Users\sergi\AppData\Local\Temp\claude\D--\f4a2342f-53ff-4bfb-827f-510fa2ff40a8\scratchpad\bt-codex30-`.

- `pytest tests/test_audit_audience_pages.py`: 20 pruebas correctas, directorio `1`.
  Cubre enlaces únicos y respuestas HTTP 200 sin redirecciones en es/en/pt,
  ausencia de Rithmic/cTrader y `guard.find_claims == []`.
- `pytest tests/test_audit_landing_audiences.py tests/test_audit_guides_seo.py`:
  25 pruebas correctas, directorio `2`.
- `pytest tests/test_audit_public_hygiene.py -k retos`: 9 pruebas correctas y
  2107 no seleccionadas, directorio `3`.
- `pytest tests/test_audit_audience_pages.py -k retos`: 6 pruebas correctas y
  14 no seleccionadas, directorio `5`, tras añadir la comprobación explícita
  del vocabulario del contenido principal.
- `ruff check .`: sin errores. `ruff format --check` sobre los tres archivos
  Python modificados: sin cambios necesarios. Archivos modificados con LF;
  `git diff --check` sin incidencias.
- `mypy src`: cuatro errores preexistentes en Windows, descritos abajo.
- `mypy --platform linux src`: sin errores en 443 archivos.

## Limitación de la comprobación en Windows

`mypy src` informa cuatro errores `attr-defined` en
`src/quant_trade/audit/pdf_tables.py:167-168`: `resource.setrlimit`,
`resource.RLIMIT_AS` y `resource.RLIMIT_CPU` no figuran para el destino Windows.
Ese archivo coincide con `origin/main` y queda fuera del cambio. La comprobación
con destino Linux termina sin errores; no sustituye el resultado de Windows.

El sandbox bloqueó inicialmente el arranque del intérprete base de Python.
Las comprobaciones se ejecutaron después con permiso ampliado. Pytest muestra
una advertencia preexistente de Starlette sobre `httpx` en `TestClient`.
