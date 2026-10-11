# Codex 26: tipado de tests y textos del comparador

La limpieza conserva los datos de las pruebas, las cifras, las clases, las etiquetas de
evidencia, los presets y el simulador. No modifica archivos JSON guardados ni sus claves.

## Cambios

- `mypy_path` apunta a `src` desde el directorio de `pyproject.toml`. Con
  `no_site_packages = true`, `PYTHONPATH` por sí solo no hacía que mypy resolviera el
  paquete: algunas firmas se trataban como `Any`. Ahora las tandas y la ejecución
  completa comprueban las firmas reales, sin exclusiones nuevas ni supresiones globales.
- Los tests usan anotaciones para fixtures heterogéneos, `Sequence` cuando sólo leen
  colecciones, `cast` y comprobaciones de opcionales. Los callbacks conservan sus efectos
  y sus valores de retorno. Se retiran únicamente `ignore` obsoletos al resolver `src`.
- En `test_audit_user_accounts.py` se retira una definición de `_seeded_file` que otra
  definición posterior ocultaba. Permanece la implementación efectiva de 500 filas;
  ningún test cambia los datos que utilizaba.
- `guides_seo` ya separaba la variable `GuideText` de los fragmentos de texto en la base
  recibida; no necesitó cambios de tipado.
- El comparador utiliza «Alcanza el objetivo», «Reaches the target» y «Atinge a meta»,
  también en la columna de la regla del mejor día, explicaciones y resúmenes.
- Las dos notas visibles de `firmfit.py` también hablan de alcanzar el objetivo. Sólo
  cambia su texto en resultados nuevos; siguen existiendo las traducciones de las notas
  antiguas para leer informes previos. Las claves `pass`, `pass_within_best_day` y los
  demás campos se conservan.
- La regresión cubre el texto visible en es/en/pt, tablas con y sin escenarios, resúmenes
  uniformes, cabeceras exactas, notas nuevas y antiguas, y `find_claims(...) == []`.

## Comprobaciones

Python: `D:\wt\.venv-pp\Scripts\python.exe`; `PYTHONPATH=D:\wt\codex-26\src`.
Los tests se ejecutan con `--basetemp` bajo el directorio de scratchpad indicado,
con nombres `bt-codex26-<n>` y tandas de uno a tres archivos.

- Revisión de todo `tests/` con mypy por tandas, seguida de
  `mypy tests --follow-imports=silent`: **438 archivos sin errores**.
- `mypy src --platform linux`: **443 archivos sin errores**, con el mismo destino que
  `.github/workflows/ci.yml` (`ubuntu-latest`).
- `ruff check .`, formato de los archivos modificados incluidos en los manifiestos de CI,
  finales LF y `git diff --check`: sin incidencias.

Las once suites solicitadas pasaron:

| Archivos `tests/test_audit_*.py` | Resultado |
| --- | --- |
| `firm_fit`, `firm_columns` | 49 passed |
| `firm_review_fixes`, `firm_fit_folded` | 52 passed |
| `challenge_sizing`, `fund_verdict` | Sin fallos; el fallo de memoria de su tanda fue en `guides_seo`, repetido después |
| `landing_compra` | Sin fallos; tanda con `b3` y `costs`: 57 passed |
| `guides_seo` | 17 passed en repetición secuencial |
| `winrate` | 27 passed en repetición secuencial |
| `sample_publication` | 28 passed en repetición secuencial |
| `portuguese_report` | 17 passed en repetición secuencial |

Otras seis tandas completas sobre 18 archivos no-audit sumaron **309 passed**.
No se presenta como ejecutada la suite completa de pytest: otras tandas adicionales
se interrumpieron por la presión de memoria y se sustituyeron por verificaciones
concretas de los auxiliares y callbacks ajustados: **15 passed** en cuatro tandas secuenciales.

## Limitación del entorno Windows

`mypy src` con el destino nativo de Windows devuelve cuatro errores preexistentes en
`src/quant_trade/audit/pdf_tables.py`, líneas 167–168: los stubs de `resource` para Windows
no definen `setrlimit`, `RLIMIT_AS` ni `RLIMIT_CPU`. Este archivo no se modifica.
La comprobación equivalente al CI pasa con `--platform linux`. Se conserva la selección
nativa de plataforma de mypy; no se ocultan estos errores con `ignore` ni se desactiva
la comprobación para Windows.

La primera ejecución simultánea de varias colas de pytest agotó memoria (`MemoryError`
y `hashlib.scrypt: malloc failure`). Esos intentos no se consideran validaciones limpias.
Se detuvieron las colas y se centralizaron las repeticiones secuenciales.
