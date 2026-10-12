# Codex 40 · Calculadora de reto insertable

Fecha: 2026-10-11. Rama: `feat/calculadora-insertable`.
Base local: `origin/main` en `6aa738e`.

## Entrega

- Widgets: `/insertar/calculadora-reto`, `/embed/challenge-calculator` y
  `/pt/incorporar/calculadora-desafio`, con la variante `/<firma>` para cada
  firma del catálogo local.
- Instrucciones: `/herramientas/insertar-calculadora-reto`,
  `/tools/embed-challenge-calculator` y
  `/pt/ferramentas/incorporar-calculadora-desafio`. Están enlazadas desde
  herramientas y aparecen en el sitemap; los widgets quedan fuera.
- Las instrucciones tienen selector GET `firm`/`locale`, vista previa y código
  iframe copiable. La altura se puede ajustar; el contenido largo se desplaza
  dentro del iframe. No se necesita JavaScript ni comunicación con la página
  que lo contiene.
- El widget comparte formulario, validación, `challenge_calc.compute` y render
  de resultados con la página normal. Reutiliza su límite de cómputos por hora.
  Reglas y supuestos se pueden desplegar sin JavaScript. CSS propio, formulario
  adaptable, tablas con desplazamiento horizontal local y pie fijo.
- El pie enlaza la calculadora normal de la misma firma e idioma con
  `?ref=embed`, `target='_blank'` y `rel='noopener'`. Los enlaces auxiliares
  también abren otra pestaña para mantener visible el widget.
- Únicamente las rutas exactas del widget permiten `frame-ancestors *`, omiten
  `X-Frame-Options`, envían `X-Robots-Tag: noindex` y apuntan su canónica a la
  calculadora normal. Sus formularios son GET y no emiten cookies, incluso
  cuando la consulta incluye `ref`. Las instrucciones permiten `frame-src 'self'`
  para la vista previa; conservan `frame-ancestors 'none'` y `DENY`,
  como el resto del sitio. No se relajan prefijos enteros.

## Conteo y privacidad

`funnel.CHALLENGE_EMBED_VIEWS_ENABLED = False` mantiene apagado el conteo de
cargas. La privacidad vigente (`legal.py`) describe visitas por día, idioma y
etiqueta y la cookie diaria `rigor_seen` para contar un navegador una vez al
día. Contar cada carga sin cookie por día y firma requiere describir otra
semántica; no se ha cambiado esa política ni se ha activado el contador.

El contador reutiliza el buffer, bloqueo y escritura diferida de `VisitCounter`.
La tabla separada `challenge_embed_views` solo tiene día UTC, firma y total;
no conserva IP, dominio que inserta, usuario ni identificadores. Las cargas
repetidas contarían por separado, sin mezclarse con las visitas del embudo.
El panel explica el estado desactivado y tiene el render de la tabla preparado.
Las pruebas activan la constante solo en memoria para comprobar la agregación.
No hay nuevo ajuste de entorno que active el contador inadvertidamente.

La etiqueta `embed` sí está permitida en la atribución existente: al abrir el
enlace del pie en la página normal se aplica el mecanismo habitual de esa
página. El iframe no lee ni escribe cookies de atribución o sesión. El límite
de cómputos mantiene el mecanismo en memoria que ya usa la calculadora normal;
esa protección no forma parte del nuevo contador agregado.

## Supuestos y límites

Herramienta de investigación con cifras declaradas y trayectorias sintéticas;
no constituye una previsión ni cambia modelos, umbrales o reglas de riesgo.
Las reglas, sus fuentes y fechas proceden de los presets locales existentes;
no se han actualizado ni consultado proveedores externos en esta tarea.
Se conservan etiquetas de evidencia y advertencias del cálculo original.
No se han añadido archivos de datos: la lista de fixtures `FROZEN` no cambia.
Precios, `legal.py` y privacidad permanecen intactos.

La revisión visual interactiva no pudo completarse: Computer Use no dispone
de un navegador conectado (inventario vacío). Se revisaron el HTML, el CSS
para anchos de 320 a 760 px y los contratos de formulario y enlaces; queda
pendiente la inspección visual en navegador en esos anchos.

## Validación

Intérprete: `D:\wt\.venv-pp\Scripts\python.exe`.
`PYTHONPATH=D:\wt\codex-40\src`. El lanzador necesita ejecutarse fuera del
sandbox para iniciar su intérprete base; se usó el mismo entorno indicado.
Pytest se ejecutó en tandas de uno a tres archivos, creando antes cada
directorio bajo
`C:\Users\sergi\AppData\Local\Temp\claude\D--\f4a2342f-53ff-4bfb-827f-510fa2ff40a8\scratchpad\bt-codex40-`.

| Tanda / archivos | Resultado |
| --- | --- |
| `challenge_embed` | 128 casos cubiertos: 120 iniciales, 2 adicionales y 9 dirigidos (3 repiten igualdad de resultados; 6 nuevos de enlaces y traducción) |
| `funnel` | 28 correctos |
| `security`, `guides_seo`, `site_copy_trust` (`core1`) | 132 correctos y 1 error de SQLite al crear la base temporal |
| `i18n`, `reading_rules`, `conversion` (`core2`) | 212 correctos y 1 error de SQLite al crear la base temporal |
| `challenge_calculator`, `challenge_sizing`, `challenge_ladder` (`calc1`) | 375 correctos |
| `public_hygiene` (`hygiene1`, única ejecución) | 2254 correctos |
| `provenance_guard` (`provenance1`) | 20 correctos |
| Caso de sitemap y reglas de traducción (`retry1`) | 3 correctos |
| Caso de conversión en español (`retry2`) | 1 correcto |

Los fallos iniciales fueron `disk I/O error` al crear un índice en
`test_every_sitemap_url_has_an_iso_lastmod_from_the_code` y
`unable to open database file` al crear una tabla en
`test_the_sample_band_follows_the_configuration[es]`. Ambos sucedieron durante
la preparación de SQLite. Cada caso pasó al repetirse en un temporal nuevo,
sin cambiar producción ni los tests para el reintento. Quedan cubiertos
satisfactoriamente los 3151 casos distintos de las suites indicadas.
La advertencia de Starlette sobre `httpx` en `TestClient` es preexistente.

- `ruff check .`: correcto.
- `ruff format --check` sobre los once archivos Python cambiados: correcto.
- `mypy --follow-imports=silent` sobre los nueve módulos de producción
  cambiados: sin errores.
- Las notas inglesas nuevas tienen regla española en `audit/i18n.py` y una
  prueba que compara la traducción con el texto nativo del widget.
- Revisión independiente de seguridad, atribución, SEO y navegación: se
  corrigieron los enlaces auxiliares que podían sacar el iframe a páginas que
  rechazan marcos; la prueba conserva `nofollow`, añade `noopener` y comprueba
  que el formulario sigue apuntando al widget.
- Archivos cambiados con LF; `git diff --check` sin incidencias.

Sin push ni PR; los cambios se dejan en commits de esta rama.
