# Codex 40 · Calculadora de reto insertable

Fecha: 2026-10-11. Rama: `feat/calculadora-insertable`.
Base local: `origin/main` en `6aa738e`; mezclada después con `origin/main`
en `504f9dd` (#513-#517), tras la revisión.

## Entrega

- Widgets: `/insertar/calculadora-reto`, `/embed/challenge-calculator` y
  `/pt/incorporar/calculadora-desafio`, con la variante `/<firma>` para cada
  firma del catálogo local.
- Instrucciones: `/herramientas/insertar-calculadora-reto`,
  `/tools/embed-challenge-calculator` y
  `/pt/ferramentas/incorporar-calculadora-desafio`. Están enlazadas desde
  herramientas y aparecen en el sitemap; los widgets quedan fuera.
- Las instrucciones tienen selector GET `firm`/`locale`, vista previa y código
  iframe copiable (`style='border:0'`, `width='100%'`). La altura se puede
  ajustar; el contenido largo se desplaza dentro del iframe. No se necesita
  JavaScript ni comunicación con la página que lo contiene. Los enlaces a los
  otros idiomas conservan la firma elegida y el idioma del widget cuando no es
  el de la página.
- En herramientas, el enlace «Insertar la calculadora de reto en tu web» va
  con los enlaces de la calculadora de reto, antes de la tabla de reglas.
- El widget comparte formulario, validación, `challenge_calc.compute` y render
  de resultados con la página normal. Reutiliza su límite de cómputos por hora.
  Reglas y supuestos se pueden desplegar sin JavaScript. CSS propio, formulario
  adaptable, tablas con desplazamiento horizontal local y pie fijo. El
  formulario envía a `#resultado` (`#result` en inglés), así que tras
  «Calcular» el iframe abre en el resultado. El widget por firma muestra el
  lead de su página, con la frase visible de no afiliación.
- El pie enlaza la calculadora normal de la misma firma e idioma con
  `?ref=embed`, `target='_blank'` y `rel='noopener'`. Los enlaces auxiliares
  también abren otra pestaña para mantener visible el widget.
- Solo el widget que renderiza `public_challenge` en sus rutas exactas (200,
  400 o 429) permite `frame-ancestors *`, omite `X-Frame-Options`, envía
  `X-Robots-Tag: noindex` y apunta su canónica a la calculadora normal: la ruta
  marca `request.state` y `_secure` solo relaja con esa marca. Un 405 o un 500
  en la misma ruta es la página de error del sitio y conserva
  `frame-ancestors 'none'` y `DENY`. El widget tiene su propia CSP, más
  estrecha: `script-src 'none'` y `form-action 'self'`, sin hash de script ni
  Stripe. Sus formularios son GET y no emiten cookies, incluso cuando la
  consulta incluye `ref`. Las instrucciones permiten `frame-src 'self'` para la
  vista previa; conservan `frame-ancestors 'none'` y `DENY`, como el resto del
  sitio. No se relajan prefijos enteros.

## Conteo y privacidad

`funnel.CHALLENGE_EMBED_VIEWS_ENABLED = False` mantiene apagado el conteo de
cargas. La privacidad vigente (`legal.py`, ya con #513) describe visitas por
día, idioma, etiqueta y grupo de página, con la cookie diaria `rigor_seen` para
contar un navegador una vez al día. Contar cada carga sin cookie por día y
firma requiere describir otra semántica; no se ha cambiado esa política ni se
ha activado el contador.

Ni el widget ni las instrucciones están en `visit_paths` ni en
`page_groups()`: no forman una familia de páginas contada y la privacidad no
necesita nombrarlas. El widget sale de `_funnel_visit` antes de cualquier
cookie o conteo. Consecuencia: las visitas a las instrucciones no se miden;
medirlas exigiría un grupo nuevo y nombrarlo en la privacidad (fuera de esta
rama). `?ref=embed` en la calculadora normal sí se cuenta, en su grupo
`calculadora-reto/<firma>` con la etiqueta `embed`.

`ChallengeEmbedViewCounter` es independiente de `VisitCounter`: su propio
bloqueo, buffer `(día, firma)`, `flush` con reintento, hilo y parada. No comparte
el tope de etiquetas de campaña ni escribe en las tablas del embudo.
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

En la primera entrega no hubo navegador conectado; la revisión posterior sí
midió el widget en navegador (ver abajo).

## Revisión y mezcla con main (2026-10-11)

Tres revisiones (seguridad, presentación y mezcla). Corregido en `625a997`:

- El marco dependía de la ruta, no de la respuesta: un 405 (POST, PUT, PATCH,
  DELETE, OPTIONS) o un 500 en una ruta del widget salía insertable. Ahora
  solo relaja el widget renderizado (`request.state`); pruebas para 405, 500 y
  HEAD.
- CSP propia del widget con `script-src 'none'` y `form-action 'self'`.
- Resultado fuera de la vista tras «Calcular» (medido a 320 y 760 px): el
  formulario envía a `#resultado`/`#result`.
- Widget por firma: lead de la firma con la no afiliación visible y título de
  reglas de la firma.
- Portugués: «empresa», como la calculadora.
- Herramientas: enlace con nombre propio, junto a la calculadora de reto.
- Instrucciones: un solo nombre accesible para el código, `style='border:0'` y
  enlaces de idioma que conservan firma e idioma elegidos.
- `ChallengeEmbedViewCounter` independiente de `VisitCounter` (la mezcla con
  #513 rompía su `flush` y su firma de `add`).

Rechazado: «la intro tiene 5 frases»; tiene 4 en es, en y pt (el punto y coma
une la tercera), dentro de las 3-4 del brief.

Mezcla `fe7f973` con `origin/main` `504f9dd`: conflictos a mano en `i18n.py`
(se conservan las reglas de main y del widget) y `store.py` (se conservan
`funnel_page_visits` y `challenge_embed_views`). Después se actualizó la
descripción de la privacidad en el comentario de `funnel.py` y en el panel.

Una revisión en navegador midió el widget a 320 y 760 px: sin desbordamiento
horizontal de la página; solo la tabla de reglas se desplaza en su contenedor;
el pie fijo (61/43 px) queda cubierto por el margen inferior.

## Validación tras la revisión y la mezcla

Sobre el árbol mezclado, una tanda de pytest a la vez, cada una con su
`--basetemp` nuevo bajo `scratchpadt40f-<tanda>`:

| Tanda | Resultado |
| --- | --- |
| `challenge_embed` | 134 correctos |
| `funnel` + `page_visits` | 245 correctos |
| `page_visit_panel` + `page_visit_store` | 20 correctos |
| `security` | 33 correctos |
| `guides_seo` | 21 correctos |
| `site_copy_trust` + `i18n` | 106 correctos |
| `reading_rules` + `provenance_guard` | 111 correctos |
| `oferta_pago` + `portuguese` | 73 correctos |
| `tools_hub` | 69 correctos |
| `challenge_calculator` | 304 correctos |
| `challenge_sizing` + `challenge_ladder` | 97 correctos |
| `owner_panel` + `share_funnel` | 63 correctos |
| `conversion` | 95 correctos |
| `public_hygiene` (una sola vez) | 2254 correctos |

`mypy --follow-imports=silent` sobre los nueve módulos de producción cambiados:
sin errores. `ruff check .` y `ruff format --check` de los once archivos
Python cambiados: correctos. LF.

## Validación inicial (`9d688d6`)

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
