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
- El filtro opcional de `Status`, acotado a las columnas de History, conserva
  `Filled` y `Partially filled`, informa de los estados excluidos y mantiene
  cierres parciales y pérdidas. Se aplica antes de seleccionar cuenta para que
  los intentos rechazados no desplacen a otra cuenta con ejecuciones.
  Avisos en es/en/pt y pruebas sin red.

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
