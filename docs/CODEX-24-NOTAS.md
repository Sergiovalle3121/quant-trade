# Codex 24 · Tarjetas OG de herramientas

Las calculadoras de reto y ruina y la tabla de reglas tienen tarjetas propias de
1200 × 630, en español, inglés y portugués. Las 16 páginas de firmas usan una
variante de la tarjeta de reto con el nombre de la firma y el aviso de que Rigor
no está afiliado. No se incluyen marcas gráficas ni logos de las firmas.

## Rutas y metadatos

- Español: `/og/calculadora-reto.png`,
  `/og/calculadora-reto-<firma>.png`, `/og/calculadora-ruina.png` y
  `/og/reglas-prop-firm.png`.
- Inglés y portugués: las mismas rutas con prefijo `/en` o `/pt`.
- Cada página enlaza su ruta absoluta en `og:image` y `twitter:image` mediante
  `PageMeta.image_path`. Los parámetros de los formularios, filtros y referencias
  no cambian la imagen ni crean entradas de caché.

## Generación y límites

`tool_cards.py` genera SVG propios y los convierte mediante `raster.card_png`.
La caché es local a cada aplicación, está protegida con un bloqueo y sólo admite
las 57 combinaciones del catálogo. Guarda únicamente conversiones correctas.
Las peticiones de imágenes no consultan la base de datos ni la red, no escriben
archivos y no generan cookies ni visitas del embudo.

Las tres imágenes OG predeterminadas se leen una vez al crear la aplicación.
Si falta CairoSVG, su biblioteca nativa o falla la conversión, la ruta devuelve
la imagen predeterminada de su idioma con estado 200 y tipo `image/png`. Esa
respuesta lleva `Cache-Control: no-store`, para permitir la recuperación; las
tarjetas generadas llevan `public, max-age=86400`. La caché recuerda el último
fallo durante 30 s (`FAILURE_TTL`, reloj monotónico) y en ese plazo responde con
la imagen predeterminada sin reintentar la importación de CairoSVG bajo el
bloqueo; pasado el plazo vuelve a intentarlo, así que instalar o reponer Cairo
no exige reinicio ni vaciado de caché.

Son imágenes descriptivas de las herramientas, independientes de los resultados
y de los datos introducidos. No presentan resultados medidos ni declaraciones
de un cliente, y no expresan promesas. El total de firmas procede del catálogo
existente. No se modifican cálculos, presets ni motor. Los textos visibles y
accesibles se someten al guard de afirmaciones: las 57 combinaciones se
comprueban al crear la aplicación (un desacuerdo con el guard impide arrancar,
y las pruebas lo detectan antes del despliegue) y, si el guard rechazara un
texto durante una petición, la ruta sirve la imagen predeterminada con
`no-store`, nunca un 500.

## Validación

Pruebas ejecutadas con el Python indicado, `-q -p no:cacheprovider`, en tandas de
uno a tres archivos y con directorios `bt-codex24-<n>` bajo el `scratchpad`
solicitado. Los nombres de la tabla omiten el prefijo `test_audit_` y `.py`.

| Archivos | Selección `-k og` | Suite completa |
| --- | ---: | ---: |
| `calculator_card`, `reading_png`, `tool_cards` | 30 correctas | 94 correctas |
| `challenge_calculator`, `ruin_calculator`, `prop_rules_table` | 4 correctas | 380 correctas |
| `guides_seo`, `public_hygiene` | 27 correctas | 2.052 correctas |

Estas ejecuciones finales no tienen fallos ni pruebas omitidas. Las 57 rutas se
comprueban contra PNG realmente generados, con firma PNG e IHDR de 1200 × 630,
y con la base de datos y la red bloqueadas durante las peticiones. También se
verifican todos los metadatos OG/Twitter, el vocabulario, las traducciones, el
límite de la caché, los parámetros irrelevantes y la ausencia de cookies.
Cada variante tiene cobertura de fallback por importación ausente y error de
conversión, seguida de recuperación, sin releer la imagen predeterminada.

Se revisaron visualmente cuatro PNG: reto en español, reto de Alpha Capital
Group en portugués, ruina en inglés y tabla de reglas en portugués. Todos
conservan el texto completo y legible.

La precarga usa el directorio de recursos empaquetados, independiente del
directorio de fotos opcionales que sustituyen las pruebas de la página de inicio.
La tanda adicional de `raster`, `reading_png_cache` y `landing_compra` terminó
con 64 pruebas correctas: 2.587 pruebas completas en total, además de las
selecciones OG anteriores.
La advertencia de deprecación de Starlette/httpx que emiten las pruebas es ajena
a estas tarjetas.

`mypy --follow-imports=silent`, `ruff check` y `ruff format --check` pasan en los
seis archivos Python modificados o añadidos. `git diff --check` pasa y todos los
archivos del cambio conservan LF. No quedan requisitos de la tarea pendientes.

### Entorno Windows utilizado

El venv indicado no contenía CairoSVG ni una biblioteca Cairo nativa al iniciar
la tarea. Se instaló `CairoSVG 2.9.1` en `D:\wt\.venv-pp` (la dependencia ya figura
en el extra `web` del proyecto). Para la validación local se extrajo
[Cairo portátil 1.17.2](https://github.com/preshing/cairo-windows/releases/tag/1.17.2)
en `%TEMP%\codex24-cairo`, sin instalar componentes del sistema ni incorporar
binarios al repositorio. El ZIP utilizado tiene SHA256
`2b9ebc56a359a91f4d0b75ed137404639c8f34e8f56513d8ff2c9549453012c2`.

Los procesos de pruebas y render usan estas variables (no son cambios
permanentes del entorno):

```powershell
$env:PYTHONPATH = 'D:\wt\codex-24\src'
$env:CAIROCFFI_DLL_DIRECTORIES = "$env:TEMP\codex24-cairo\cairo-windows-1.17.2\lib\x64"
$env:PATH = $env:CAIROCFFI_DLL_DIRECTORIES + ';' + $env:PATH
```

El servidor sigue usando el manejo opcional existente de `raster.py`: no necesita
esta preparación local para servir las imágenes predeterminadas. Las pruebas de
PNG real detectan explícitamente el fallback y no lo aceptan como una tarjeta
generada.

## Revisión del 11 de octubre

- La tarjeta de la tabla de reglas dice «de prop firms» en español y portugués,
  igual que el `nav` de su página (`rules_table.py`); en inglés ya coincidía.
- La etiqueta superior derecha es «TOOLS» en inglés, con la misma información
  que «HERRAMIENTAS» y «FERRAMENTAS».
- La revisión visual se hizo con Arial (Windows); el servidor rasteriza con
  DejaVu Sans, la única fuente de `Dockerfile.web`, entre un 12 % y un 16 % más
  ancha. Los anchos máximos medidos con DejaVu dejan al menos 200 px de margen
  entre el texto más largo y el motivo documental (x = 916), y la nota inferior
  no alcanza el pie «rigorscore.com».
- El pie imprime sólo «rigorscore.com», sin la ruta de la página, a diferencia
  de la tarjeta de la calculadora de suerte: la ruta de firma más larga ocuparía
  unos 630 px a 22 px con DejaVu y pisaría la nota en español; la tarjeta OG
  siempre acompaña al enlace de su página.
- Pruebas de esta revisión (mismo Python, `-q -p no:cacheprovider`, Cairo
  portátil presente): `tool_cards` completo 24 correctas (tres nuevas: memoria
  breve del fallo, guard al arrancar y guard en una petición); la tabla de
  arriba recoge los nuevos totales. `mypy --follow-imports=silent`, `ruff check`
  y `ruff format --check` limpios en `tool_cards.py`, `web.py` y la prueba.
