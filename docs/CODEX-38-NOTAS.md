# Codex 38 · Qué mandar, plantilla CSV y NDA institucional

Fecha: 2026-10-11. Rama: `feat/institucional-que-mandar`.

## Cambios

- «Qué mandar», «What to send» y «O que enviar» aparecen inmediatamente después
  de los entregables y antes del formulario. Incluyen retornos o NAV, benchmark,
  variantes, periodo reservado y supuestos de costos.
- El operador firma un NDA mutuo antes de recibir los archivos y acepta el del
  cliente. El primer informe y el nombre de la empresa requieren permiso escrito
  para publicarse. La confirmación del formulario recuerda el NDA y deja de pedir
  ambas series como si fueran obligatorias.
- Las condiciones aclaran que la revisión no concilia cifras con el bróker ni
  con el administrador, no es diligencia operativa ni una presentación GIPS.
- Una descarga compartida en `/revision-institucional/plantilla.csv` ofrece cuatro
  filas ficticias, con fechas mensuales, retornos positivos, negativos y cero.
  El enlace, la explicación y el nombre del archivo identifican el ejemplo ficticio.
  Responde con `text/csv`, `Content-Disposition: attachment` y
  `X-Robots-Tag: noindex`. Permite rastreo para leer el encabezado y no
  entra en el sitemap. Se actualiza la fecha de la oferta a 2026-10-11.
- Se mantienen los precios, `legal.py` y la política de privacidad. No cambian
  importadores, cálculos ni criterios estadísticos. La copia nueva no lleva
  prefijos de evidencia en prosa y sus avisos ingleses tienen reglas españolas.

## Formato compatible y límites

Se usa la alternativa prevista en la tarea: `date,gross_return,net_return,benchmark`.
El importador de producción reconoce `gross_return` y `net_return`, pero no
`portfolio_gross` ni `portfolio_net`. Las columnas extra de variantes se ignoran
en la tabla de retornos; incluirlas allí perdería su significado para el análisis.
Por eso la página pide las variantes en otro CSV: `date,variant_1,variant_2`, una
columna por variante y las mismas fechas que la cartera. Si solo se conoce el
número de intentos, se conserva como declaración.

La plantilla usa fracciones y punto decimal (`0.01 = 1 %`). La página indica
sustituir las cuatro filas por el historial completo y quitar las columnas de neto
o benchmark si no se dispone de esas series. Cuatro filas ilustran el formato;
no constituyen evidencia suficiente para una revisión estadística. El importador
de variantes requiere al menos 16 observaciones. No se amplía ese umbral.
La página dice esos límites del importador: al menos 2 variantes y 16 fechas,
hasta 500 variantes y 5 MB, sin celdas vacías.

No fue necesario cambiar contadores fijos de claves o rutas en tests: las claves
siguen siendo iguales entre idiomas y el inventario HTML conserva sus páginas.
La ruta CSV compartida se prueba expresamente fuera del sitemap.

## Validación

Intérprete: `D:\wt\.venv-pp\Scripts\python.exe`.
`PYTHONPATH=D:\wt\codex-38\src`. Tandas de uno a tres archivos, con carpetas
temporales creadas bajo el prefijo solicitado `scratchpad\bt-codex38-`.

- Plantilla y sección: 10 pruebas correctas, temporal `21`. La descarga se lee
  mediante `import_return_series` y `build_inputs`, conservando las cuatro fechas,
  bruto, neto y benchmark, sin inventar variantes.
- Administración y correo institucional: 21 pruebas correctas, temporal `2`.
- Ejemplo, formulario y audiencia institucional: 70 pruebas correctas, temporal `1`.
- `test_audit_i18n.py` y `test_audit_conversion.py`: 122 pruebas correctas,
  temporal `3`.
- `test_audit_site_copy_trust.py` y `test_audit_guides_seo.py`: 100 pruebas
  correctas, temporal `4`.
- `test_audit_public_hygiene.py`: 2.227 pruebas correctas, temporal `5`.
- `test_provenance_guard.py`: 20 pruebas correctas, temporales `6` y `7`
  (la última ejecución incluye estas notas finales). No se cambia el techo de deuda.
- Total de casos en las tandas finales, sin contar repeticiones: 2.570 correctos.
- Ruff global y mypy con `--follow-imports=silent` sobre los módulos modificados:
  sin errores. El archivo de tests nuevo también supera Ruff y mypy.
- `ruff format --check` sobre los cuatro archivos Python modificados: sin cambios
  necesarios. Archivos modificados con LF; `git diff --check` sin incidencias.
- `mypy --follow-imports=silent --platform linux src`: sin errores en 445 archivos.

## Correcciones tras la revisión

- Punto 1: si hay bruto y neto, van como retornos en las columnas `gross_return`
  y `net_return` del mismo CSV, como en la plantilla; una serie de NAV lleva una
  sola columna (`schema.parse_equity_csv` lee una sola `nav`). Punto 2: el índice
  puede ir aparte o como columna `benchmark` del mismo CSV (también al lado de un
  NAV).
- Punto 3: límites de `_parse_variants_csv` y de subida (2 variantes, 16 filas,
  500 columnas, 5 MB, sin celdas vacías). Un test nuevo sube una cartera con los
  encabezados de la plantilla y un CSV `date,variant_1,variant_2` de 20 fechas:
  `variants.shape == (20, 2)` y `variant_validation["status"] == "MEASURED"`; otro
  liga las cifras de la página con `MAX_VARIANTS`, `MAX_UPLOAD_BYTES` y los
  rechazos `too_few_variants` y `too_few_variant_rows`.
- Persona: la página usa «nosotros + tú»; la línea del NDA y la confirmación del
  formulario pasan a «Firmamos… antes de que nos mandes nada; puedes mandar el
  tuyo» (en/pt equivalentes). El sentido del correo se mantiene; solo cambia la
  persona gramatical.
- La nota del formulario aclara que no hace falta escribir datos confidenciales:
  la serie y los detalles van después del NDA.
- «Periodo reservado (fuera de muestra)», «Out-of-sample (holdout) period» y
  «Período reservado (fora da amostra)», como el campo del formulario de subida.
  En inglés, «before freezing the rules» y «the rules have stayed fixed».
- Publicación: «Ningún informe, tampoco el primero, se publica…», para no sugerir
  que los informes siguientes sí podrían publicarse.
- Límites con sujeto: «La revisión no concilia…». En portugués, «due diligence
  operacional» y «Se tiver as séries das variantes».
- La plantilla envía `X-Robots-Tag: noindex`, el literal de los demás adjuntos del
  sitio. Los PDF públicos de ejemplo no llevan esa cabecera porque son muestras
  que se enlazan; la plantilla es un archivo ficticio sin contenido que buscar.
- El `Cache-Control: public, max-age=3600` de la ruta lo reemplaza el middleware
  por `no-store`, igual que en los PDF de ejemplo. No se cambia aquí.

## Limitación de mypy en Windows

`mypy --follow-imports=silent src` informa cuatro errores `attr-defined` en
`src/quant_trade/audit/pdf_tables.py:167-168`: `resource.setrlimit`,
`resource.RLIMIT_AS` y `resource.RLIMIT_CPU` no figuran para el destino Windows.
Ese archivo coincide con `origin/main` y queda fuera del cambio.
La comprobación con destino Linux termina sin errores; no sustituye el resultado
del destino Windows. Esta es la única comprobación solicitada que no queda limpia.

El sandbox impidió inicialmente arrancar el intérprete base de Python. Se pudieron
ejecutar las comprobaciones con permiso ampliado, sin instalar ni cambiar el
entorno. Pytest informa una advertencia preexistente de Starlette sobre `httpx`.
