# Codex 37 · Ejemplos calculados en herramientas

Fecha: 2026-10-11. Rama: `feat/herramientas-ejemplos`.
Base local: `origin/main` en `94ee9d0`.

## Cambios

- Las tarjetas de `/herramientas`, `/en/tools` y `/pt/ferramentas` muestran un
  ejemplo con etiqueta Declarado y un enlace «Ver este ejemplo», traducidos.
- `tools_examples.py` obtiene los resultados de las mismas funciones que usan
  las calculadoras y el lector. Los enlaces reutilizan sus parámetros públicos.
- La tabla de reglas permanece dentro de la tarjeta de reto. Su ejemplo cuenta
  firmas y programas desde los presets y usa la fecha de lectura más reciente.
- `TOOL_KEYS`, los resúmenes y sus advertencias permanecen intactos. El ItemList
  existente conserva sus seis entradas y no incorpora resultados calculados.

## Supuestos y límites

Son casos ilustrativos declarados, sin archivos de clientes ni datos de mercado.
Sus resultados dependen de los supuestos de cada herramienta y no son mediciones
de un historial. No cambian los modelos, las reglas de riesgo ni sus umbrales.
El modelo de suerte usa rendimientos diarios, asimetría cero y colas normales.
El intervalo de aciertos es el de Wilson al 95 % y supone operaciones independientes.
El reto simula las dos fases del programa elegido con sus reglas fechadas.
Con el caso solicitado devuelve 100,0 % en sus simulaciones, limitado a 250 días
hábiles por fase; se muestra como resultado del modelo y no como una predicción.
La ruina distingue operaciones del historial, horizonte simulado y riesgo por
operación; el umbral es una pérdida respecto al saldo inicial. Los modelos no
describen dependencias reales entre operaciones ni todos los costes de ejecución.
La fecha de la tabla corresponde a los presets locales, sin revisión de fuentes
externas durante esta tarea.

### Excepciones a los enlaces con consulta

- **Comprobación de informes:** la herramienta solo calcula una huella al recibir
  un archivo por POST y compararla con el registro de archivos emitidos. No existe
  un parámetro de consulta que reproduzca una comprobación. El caso público es el
  PDF de ejemplo (`/ejemplo.pdf`, `/sample.pdf`, `/pt/exemplo.pdf`): el servicio
  lo registra como informe de ejemplo al generarlo y `/comprobar` responde «Es el
  informe de ejemplo de Rigor, sin cambios». La tarjeta enlaza ese PDF y abre el
  formulario; no presenta huella, fecha ni resultado inventados.
- **Tabla de reglas:** el ejemplo describe el catálogo completo. Abre la tabla
  sin filtros; añadir un filtro cambiaría los conteos que se muestran.

## Revisión del 11 de octubre

Cambios tras la revisión de la rama (HEAD `c94c895`):

- Los enlaces «Ver este ejemplo» llevan la misma consulta que `share_url`
  pero sin `ref`: esas etiquetas (`calculadora`, `aciertos`, `reto`, `ruina`,
  `lectura`) significan «compartida» en `/panel`, y un visitante directo que
  pulsara el ejemplo quedaba atribuido 30 días a un compartido (cookie
  `rigor_ref`). Un test comprueba que el enlace del hub no deja la cookie y que
  el de compartir sí.
- El intervalo de aciertos del hub se escribe con `articles.win_rate_interval`,
  la misma función que la página de destino («44,6–73,7 %»), de modo que la
  cadena del ejemplo aparece literalmente en el destino; el test ya no
  documenta una excepción de formato.
- El ejemplo de reto mantiene los insumos del brief (50 %, 1,5R/1R, 0,5 %,
  3/día, FTMO 2-Step) y su 100,0 %; el texto lo presenta como resultado del
  modelo y muestra en la misma línea las cuotas que tocan el límite diario y el
  total (0,0 % y 0,0 %), también tomadas de `challenge_calc.compute`. Cambiar
  el caso es decisión de Sergio; con la misma función: riesgo 1 % → 96,6 %
  (3,4 % toca el límite total); riesgo 2 % → 28,4 % (71,6 % toca el límite
  diario); 45 %, riesgo 1 %, 2/día → 77,5 % (22,5 % toca el límite total).
- La tarjeta de comprobación ya no cita un «informe JSON de ejemplo» que el
  sitio no ofrece: señala el PDF de ejemplo, lo enlaza para descargarlo y dice
  lo que la comprobación responde al elegirlo (texto existente en `check.py`).
- La línea «Ejemplo:» lleva `margin-top:16px` (como la lista que la precede;
  `.article-cta p` pone los márgenes a 0), de modo que no queda pegada a «Sin
  registro» a 375 px.
- La nota de evidencia es la misma cadena que usa el lector
  (`public_card.COPY["computed"]`, «Calculado a partir de lo declarado»); la
  tabla de reglas lleva una nota propia («Contado en las reglas publicadas») y la
  comprobación no lleva nota. La insignia Declarado se mantiene en las siete
  tarjetas, como pedía el brief.
- Reglas de `i18n.py` actualizadas para las notas y el texto nuevo de
  comprobación.

## Validación

Intérprete: `D:\wt\.venv-pp\Scripts\python.exe`.
`PYTHONPATH=D:\wt\codex-37\src`.
Pytest se ejecuta en tandas de uno a tres archivos y con directorios bajo
`C:\Users\sergi\AppData\Local\Temp\claude\D--\f4a2342f-53ff-4bfb-827f-510fa2ff40a8\scratchpad\bt-codex37-`.

El sandbox impide arrancar el intérprete base de ese entorno; las comprobaciones
usan el mismo Python con permiso ampliado.

### Pytest

El filtro solicitado fue `-k 'herramientas or tools or ferramentas'`:

| Archivos | Temporal | Resultado |
| --- | --- | --- |
| tools_hub, winrate, challenge_calculator | filtro-1 | 70 correctas, 3 fallos de expectativas de formato, 324 no seleccionadas |
| ruin_calculator, calculator, guides_seo | filtro-2 | 3 correctas, 68 no seleccionadas |
| public_hygiene | filtro-3 | 27 correctas, 2143 no seleccionadas |

Cada suite también se ejecutó completa una vez:

| Archivos | Temporal | Resultado |
| --- | --- | --- |
| tools_hub | test-agent-1 | 62 correctas, los mismos 3 fallos de formato y 1 error al preparar SQLite |
| winrate, challenge_calculator | completo-1 | 331 correctas |
| ruin_calculator, calculator, guides_seo | completo-2 | 70 correctas, 1 fallo del límite de tiempo |
| public_hygiene | completo-3 | 2170 correctas |

El destino de aciertos escribe un solo signo `%` al final del intervalo; los
tests nuevos exigían uno junto a cada límite. Se corrigió la comparación del
destino con su formato editorial, conservando la comprobación de ambos límites
recalculados en el ejemplo. El error de SQLite (`unable to open database file`)
ocurrió antes de ejecutar el caso de reglas en español. La repetición enfocada
de aciertos, ruina y reglas en es/en/pt terminó con **9 correctas** y 57 no
seleccionadas (`test-agent-2`), incluido ese caso de SQLite y la comprobación
adicional de la tasa del límite inferior de ruina.

La prueba `test_the_worst_case_fits_the_time_and_memory_budget` tardó 2,1218 s,
frente al límite de 2 s, durante las tandas paralelas. Se repitió sola después
de terminar las demás: **1 correcta** (`rendimiento`), sin tocar el modelo, la
prueba ni su umbral. Los 2638 casos distintos de las siete suites quedaron
cubiertos satisfactoriamente entre la ejecución completa y estos reintentos;
no se ocultan los fallos iniciales en las tablas anteriores.

Los tests nuevos recalculan desde la consulta enlazada, exigen HTTP 200 y buscan
los resultados en la tabla o tarjeta de destino. También comprueban las etiquetas
Declarado, `guard.find_claims == []`, los conteos y fechas de reglas, la traducción
de notas y el ItemList sin resultados añadidos. No acceden a la red. Pytest muestra
una advertencia preexistente de Starlette sobre `httpx` en `TestClient`.

### Análisis estático

- `ruff check .`: sin incidencias; `ruff format --check` sobre los cinco archivos
  Python modificados: sin cambios necesarios.
- `mypy --follow-imports=silent` sobre esos cinco archivos: sin errores.
- `mypy --follow-imports=silent src`: cuatro errores preexistentes de Windows en
  `pdf_tables.py:167-168`, por `resource.setrlimit`, `RLIMIT_AS` y `RLIMIT_CPU`.
  El archivo coincide con `origin/main`; no se modifica en esta tarea.
- `mypy --follow-imports=silent --platform linux src`: sin errores en 445 archivos.
  Esta comprobación no sustituye el resultado con destino Windows.
- Archivos modificados con LF; `git diff --check` sin incidencias.

### Validación de la revisión del 11 de octubre

Sobre `06c5f92` (los cambios de la sección anterior), mismo intérprete y
`PYTHONPATH`, temporales `bt-rc37-10` a `bt-rc37-15` (borrados al terminar):

| Archivos | Resultado |
| --- | --- |
| tools_hub, winrate, challenge_calculator | 400 correctas |
| ruin_calculator, calculator, guides_seo | 71 correctas (incluido el presupuesto de tiempo) |
| public_hygiene `-k herramientas` | 9 correctas, 2161 no seleccionadas |
| i18n, site_copy_trust | 102 correctas, 3 fallos preexistentes |

Los tres fallos (`test_every_importer_fixture_is_fully_translated[sierra_chart_trades.txt]`,
`test_no_article_paragraph_starts_with_an_evidence_label` y
`test_no_sitemap_page_shows_internal_paths_labels_or_raw_sizes`, ambos sobre el
artículo `regla-de-consistencia-prop-firm`) se reproducen idénticos en `c94c895`
desde un worktree desprendido; la rama no toca artículos ni importadores y en
`main` ya existen `fix/ci-sierra-fixture` y `fix/ci-copy-trust-provenance` para
ellos. `ruff check` y `ruff format --check` sobre los cinco archivos Python:
limpios; `mypy --follow-imports=silent` sobre ellos: sin errores; LF y
`git diff --check` sin incidencias.
