# Codex 27: guía de exportación de cTrader

Fecha: 2026-10-11. Rama: `feat/guia-ctrader`.

## Alcance

- Guía `ctrader` en español, inglés y portugués, con una fuente oficial de
  `help.ctrader.com` junto a cada paso y aviso de no afiliación a cTrader ni Spotware.
- Ruta documentada: Trade Watch > History > Statement > Save. Desktop describe
  extractos HTML o `.xlsx`; Web y Mac, HTML; los tres documentan guardado CSV.
- Portada, capacidades, enlaces a calculadora de reto y tabla de reglas,
  sitemap y fechas propias actualizados al 2026-10-11.
- Fixture sintético con columnas documentadas de History, sin datos de una cuenta.
  No representa una cabecera oficial del CSV, que la documentación no enumera.
- No se añadió un formato nativo: se conserva el lector universal y se explica
  renombrar el resultado bruto monetario a `profit`, manteniendo comisiones y swap
  en la misma moneda y comparando valores y totales con el original.
- El filtro opcional de `Status`, acotado a las columnas de History, excluye
  solo los cuatro estados sin ejecución que documenta la ficha «Deal
  information» de la página History de Desktop (Rejected, Error, Missed,
  Internally rejected), conserva Filled, Partially filled y cualquier otro valor
  (vacío o de otro vocabulario), informa de los estados excluidos y mantiene
  cierres parciales y pérdidas. Se aplica antes de seleccionar cuenta para que
  los intentos rechazados no desplacen a otra cuenta con ejecuciones. Si todas
  las filas quedan excluidas, el rechazo `deals_without_execution` nombra los
  estados vistos. Avisos y rechazo en es/en/pt y pruebas sin red.
- Alias aditivos en el lector universal para los nombres de Mac: `Broker
  commission` y `Conversion fee` se suman como comisiones; `Swaps` ya se
  reconocía. Las 19 lecturas de las muestras de `tests/fixtures/audit_imports`
  (con y sin mapeo) dan el mismo resultado byte a byte con el código de
  d37e500 y con el de esta rama.

## Fuentes leídas en la revisión del 11 de octubre de 2026

- https://help.ctrader.com/ctrader/trading/history/ — «Deal information»:
  «Status – the current status of the Deal»: Filled, Partially filled,
  Rejected, Error, Missed, Internally rejected. Respalda el consejo de la guía
  sobre Status y la lista de exclusión del lector.
- https://help.ctrader.com/ctrader-mac/trade/trade-watch/ — «History columns»:
  Swaps, Broker commission, Conversion fee, Gross (currency), Net (currency),
  Gross USD, Net USD; «Click the Statement button to open the HTML account
  statement in a new tab, where you can save it locally as a CSV file or print
  it» (sin botón Save ni ubicación del botón Statement).
- https://help.ctrader.com/ctrader-web/interface/user-time-offset/ — «To set
  the time zone, click Current time at the bottom right…»; «The new user time
  will apply to all time and date information displayed on the charts and
  your trade details». Misma redacción que la página de Desktop; el paso 1
  cubre Desktop y Web y la página figura en las fuentes de la guía.

## Hallazgos de la revisión aplicados en la rama

- Guía: la lista de columnas queda acotada a Desktop y se añaden las de Mac;
  la subida explica que el lector reconoce Swaps, Broker commission y
  Conversion fee, que Gross (currency) debe renombrarse a `profit` y que las
  copias en USD se quitan porque, sin mapeo, el lector tomaría `Net USD`.
- Guía: el consejo sobre importar sin renombrar dice que el resultado saldría
  como variación de precio por lotes sin tamaño de contrato (inservible aunque
  avisado): renombrar o mapear no es opcional. Reproducido con la muestra:
  0,0005 frente a 50 con el mapeo.
- Guía: «Save» solo se atribuye a Desktop y Web; la ubicación del botón
  Statement, al FAQ de Desktop; el desfase horario, a Desktop y Web.
- Portada: la descripción en español medía 160 caracteres, el techo de
  higiene; ahora las tres quedan por debajo de 150 y vuelven a nombrar las
  plataformas que se leen tal cual, con cTrader como excepción explícita.
  `tests/test_audit_guides_seo.py` exige `<= 150`.
- `tests/test_audit_reading_rules.py`: la muestra de cTrader se fecha en
  septiembre de 2026 (la herramienta de regresión audita con un reloj fijo,
  `NOW = 2026-09-29`) y queda congelada en `FROZEN` junto con las tres muestras
  auditables de #500 que main nunca congeló; las dos que la herramienta rechaza
  (`sierra_chart_trades.txt`, cantidad sin nombrar; `topstepx_trades.csv`,
  fechas posteriores a `NOW`) se declaran en `REFUSED` con su código. El test
  `test_every_file_of_the_repository_is_frozen` ya fallaba en d37e500 por
  esas cinco muestras.
- `tests/test_audit_importers.py::test_every_warning_and_error_message_passes_the_profit_claim_guard`
  ya fallaba en d37e500 (`sierra_chart_trades.txt` sin el mapeo de `Trade
  Quantity`); el mapeo explícito del barrido corrige ese rojo previo, no
  enmascara un cambio de lectura.
- `ruff format` sobre `guides.py` (la tupla `_CTRADER_HISTORY` superaba la
  línea; CI formatea ese archivo). Docstring de `pages._guide_offer` acorde al
  enlace de firmas de futuros que cTrader omite.

## Límites

No se abrió una cuenta de cTrader ni se obtuvo un extracto real. Los pasos se
redactaron con la investigación oficial suministrada. La documentación no fija
la cabecera exportada, el alcance del filtro temporal, el efecto de ocultar
columnas ni la zona horaria del CSV. Tampoco documenta exportación Mobile ni una
ruta específica por firma de evaluación. La guía expone estas lagunas.

Declarar el desfase horario no convierte las horas. La interpretación bruto/neto
del lector existente es heurística; los totales deben contrastarse. No se añadió
conectividad, ejecución ni ninguna afirmación sobre resultados futuros.

## Validación

Se usó `D:\wt\.venv-pp\Scripts\python.exe`, con
`PYTHONPATH=D:\wt\codex-27\src`. Cada tanda de pytest utilizó un directorio
distinto bajo:

```text
C:\Users\sergi\AppData\Local\Temp\claude\D--\f4a2342f-53ff-4bfb-827f-510fa2ff40a8\scratchpad\bt-codex27-<n>
```

Las tandas cubren `test_audit_guides_futures.py`, `test_audit_guides_seo.py`,
`test_audit_guide_entry.py`, `test_audit_importers.py`,
`test_audit_universal_import.py` y `test_audit_public_hygiene.py`, tanto con
`-k ctrader` como completas. Los resultados finales se registran abajo.

| Tanda completa | Resultado |
| --- | --- |
| `test_audit_guides_futures.py` | 22 correctas |
| `test_audit_guides_seo.py` | 20 correctas |
| `test_audit_guide_entry.py` | 25 correctas |
| `test_audit_importers.py` + `test_audit_universal_import.py` | 107 correctas |
| `test_audit_public_hygiene.py` | 2 146 correctas |

Total completo: 2 320 pruebas correctas. El aviso de deprecación de Starlette
sobre `httpx` ya procede del entorno y no afecta a estos resultados.

Selección `-k ctrader`: 56 pruebas correctas entre los seis archivos (20 de
guías de exportación e importadores, 6 de SEO/entrada y 30 de higiene pública),
tras repetir la expectativa de bruto/neto corregida. `find_claims == []` en
los textos y páginas comprobados.

`mypy --follow-imports=silent`: sin errores en los siete módulos modificados
(`guides`, `guide_capabilities`, `pages`, `seo`, `universal`, `i18n`, `report_pt`).
`ruff check`: sin errores en esos módulos y los seis archivos de pruebas.
`git diff --check` limpio; todos los archivos cambiados usan LF.

Validación de la revisión del 11 de octubre (directorios
`scratchpad\bt-rc27-10` a `bt-rc27-14`, borrados al terminar):

| Tanda | Resultado |
| --- | --- |
| `test_audit_universal_import.py` + `test_audit_importers.py` | 113 correctas |
| `test_audit_guides_futures.py` + `test_audit_guide_entry.py` | 47 correctas |
| `test_audit_guides_seo.py` + `test_audit_errors_pt.py` | 38 correctas |
| `test_audit_reading_rules.py` | 91 correctas |
| `test_audit_public_hygiene.py -k "ctrader or guias or guides or title_and_description or sitemap"` | 544 correctas |

`mypy --follow-imports=silent` limpio en `universal`, `guides`, `pages` y
`errors_pt`; `ruff check` y `ruff format --check` limpios en los archivos
tocados y en toda la lista `.github/launch-python-files.txt`; `git diff
--check` limpio. `find_claims == []` en los textos propios de la guía, las tres
páginas y las tres portadas renderizadas; sin vocabulario prohibido.

Incidencias resueltas durante la validación:

- El intérprete no podía iniciar su Python base dentro del aislamiento. Su
  ejecución fuera del aislamiento fue admitida por la revisión automática.
- La primera expectativa nueva del fixture en guías usaba resultado neto donde
  `Trade.pnl` almacena bruto. Se corrigió la expectativa; las pruebas de importación
  comprueban por separado costes y neto.
- El barrido general de avisos encontraba el fixture previo de Sierra Chart sin
  su mapeo obligatorio de `Trade Quantity`. Ahora usa los mapeos explícitos de
  Sierra Chart y cTrader, sin ocultar errores del importador.
- Dos tandas completas simultáneas se interrumpieron con `MemoryError`.
  Se repitieron secuencialmente por archivo.
- Se ajustó con Ruff el formato de dos archivos de pruebas.

No se hizo push ni se abrió PR.
