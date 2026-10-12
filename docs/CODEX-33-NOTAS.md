# Codex 33 · Visitas por página

## Alcance y supuestos

- Se conserva `is_person`, el filtro GET/200, las exclusiones de robots,
  prefetch e imágenes y la cookie diaria global `rigor_seen`. El grupo describe
  la primera página contada del día por navegador; no mide todas las páginas
  vistas, usuarios únicos, recorridos ni preferencias individuales.
- Se agrupan las traducciones con el slug canónico español. La calculadora de
  reto se desglosa por la firma de su ruta publicada, nunca por parámetros de
  consulta. Su fila principal incluye todas las firmas y la página sin firma.
- Las guías, artículos y revisión institucional se incorporan a las rutas
  públicas contadas. Los índices `/guias` y `/articulos` no se incorporan: los
  grupos pedidos son los de cada slug. Las visitas que ya se contaban en
  `/ejemplos` conservan su grupo propio `ejemplos`.
- `/v/ejemplo` y `/v/ejemplo-senal` comparten `v/ejemplo`; una publicación real
  usa `v/publicacion`. Ni consultas, valores de calculadoras, IDs de informes,
  IP, user agent, cookies ni datos de cuenta entran en la dimensión de página.

## Persistencia y panel

- Migración aditiva mediante `metadata.create_all`, bajo el bloqueo de esquema
  existente en PostgreSQL. `funnel_page_visits` tiene únicamente `day`, `locale`,
  `ref`, `page_group` y `visits`; clave compuesta de las cuatro dimensiones.
- `funnel_visits` conserva esquema e historial. Las llamadas antiguas a
  `count_visit` sin grupo siguen funcionando. Las dos tablas se actualizan
  mediante UPSERT dentro de la misma transacción; un error revierte ambas y
  permite reintentar sin duplicar el contador anterior.
- Mismo contador en memoria, flush cada 60 segundos, al leer el panel y al
  cerrar. Sigue existiendo la limitación previa: una terminación abrupta puede
  perder contadores pendientes. No se reconstruyen los grupos históricos.
- «Páginas» muestra 7 y 28 días UTC incluyendo hoy; orden por visitas de 28 días,
  después 7 días y nombre. La columna por `ref` usa su ventana previa de 30 días,
  solo grupos medidos; empates por nombre y ausencia como `NOT_MEASURED`.
- Los límites de privacidad se validan en memoria, antes de persistir y al
  renderizar. El panel sigue protegido por la clave y sin caché.

## Texto de privacidad

No se modifica `legal.py`. Conviene revisar por separado una aclaración
«por grupo de página» en la descripción de los contadores agregados y nombrar
guías, artículos y revisión institucional entre las páginas incluidas. La
implementación conserva el límite de contadores diarios sin datos por persona.

## Verificación

Se usó `D:\wt\.venv-pp\Scripts\python.exe`, `PYTHONPATH=D:\wt\codex-33\src`
y tandas de hasta tres archivos con `--basetemp` bajo el directorio solicitado
(`bt-codex33-1`, `-2`, `-20`, `-21`, `-30` a `-33`, `-40` a `-42`).

| Tanda | Resultado |
| --- | --- |
| page_visits, funnel, share_funnel | 236 aprobadas |
| page_visit_store, ops_postgres | 13 aprobadas; 15 PostgreSQL omitidas |
| store, store_hooks, public_reading | 54 aprobadas |
| page_visit_panel | 6 aprobadas |
| owner_panel, funnel | 79 aprobadas inicialmente; un error de E/S SQLite pasó al repetir el caso aislado |
| ops | 11 aprobadas |
| reading_png, reading_png_cache, institutional_intake | 69 aprobadas; 3 de renderizado nativo omitidas |
| challenge_calculator, ruin_calculator, winrate | 374 aprobadas inicialmente; un error de E/S SQLite pasó al repetir el caso aislado |
| calculator_card, tool_cards, sample_publication | 88 aprobadas; 6 de renderizado nativo omitidas |

Los resultados por tanda incluyen algunas repeticiones; no deben sumarse como
número de pruebas únicas. Se recibió el aviso existente de obsolescencia de
Starlette/httpx. Los dos errores de E/S SQLite ocurrieron en la creación de
índices preexistentes, antes de ejecutar las comprobaciones de las pruebas.
Ambos casos pasaron al repetirse y no quedan fallos funcionales pendientes.

- `ruff check src tests`: aprobado. `ruff format --check` de los 12 archivos
  Python modificados: aprobado. `git diff --check`: aprobado; archivos en LF.
- `mypy src --follow-imports=silent`: cuatro errores previos en Windows en
  `pdf_tables.py:167-168` (`resource.setrlimit`, `RLIMIT_AS`, `RLIMIT_CPU`). Ese
  archivo no se modifica. Con `--platform linux`, la plataforma del servicio:
  aprobado, 444 archivos.
- PostgreSQL no se ejecutó localmente porque falta `QA_POSTGRES_URL`. Se amplió
  el archivo que ejecuta `postgres-staging` con migración desde esquema previo,
  preservación de historial, concurrencia y reversión/reintento atómico.
- Las pruebas de renderizado nativo CairoSVG se omiten por la biblioteca nativa
  ausente. Las pruebas de lectura y PNG con el renderizador simulado sí pasan.

## Revisión posterior (hallazgos aplicados sobre 29a1fa5)

- `_funnel_visit` envuelve `visits.add` en `try/except ValueError` y registra un
  aviso con el grupo (nunca la ruta ni la consulta): si `visit_paths` y
  `page_groups()` divergieran, la página seguiría respondiendo 200 sin contar.
- `VisitCounter.add` acota las etiquetas de campaña no listadas
  (`CAMPAIGN_TAG` sin entrada en `REF_TAGS`): como máximo
  `MAX_PENDING_CAMPAIGN_REFS` (200) distintas por lote de flush; las siguientes
  se cuentan como directo con un aviso. Un lote que falla al escribir conserva
  sus etiquetas dentro del tope. Herencia de la base, no regresión de la rama.
- `/panel` lee los grupos guardados por forma (`shaped_page_group`: segmentos
  `[a-z0-9-]`, máximo dos, 96 caracteres) en lugar de por pertenencia al
  catálogo vivo: un slug renombrado o una firma retirada conserva su historial.
  La escritura (`VisitCounter.add`, `Store.count_visit`) sigue siendo estricta.
- `test_privacy_text_names_every_counted_page_family` ata el párrafo de la
  política que nombra `rigor_seen` a las familias de `page_groups()`. Las que
  el texto aún no nombra están en `LEGAL_TEXT_PENDING` con la palabra que se
  espera en es/en/pt; cuando `legal.py` las nombre, el test falla hasta subirlas
  a `LEGAL_NAMES`. Hallazgo adicional: ya en la base 94ee9d0 se contaban la
  tabla de reglas (`reglas-prop-firm`) y las páginas públicas de verificación
  (`/v/<id>`, `/v/ejemplo`) sin que el texto las nombrara.

### Propuesta de texto para la PR hermana sobre `legal.py`

Sustituir en el párrafo del contador (es/en/pt) la lista de páginas y las
dimensiones; los tres textos deben seguir pasando el guard:

- es: «las visitas a la página principal, a las de cada caso, a las guías, a
  los artículos, a la revisión institucional, a las páginas públicas de
  verificación y a las herramientas gratis (calculadoras, tabla de reglas,
  tarjeta de cifras, ejemplos y página de herramientas) se cuentan por día,
  idioma, etiqueta del enlace (…) y grupo de página (un nombre corto de la
  página, nunca la dirección completa ni sus parámetros), sin dirección».
- en: «visits to the home page, the case pages, the guides, the articles, the
  institutional review, the public verification pages and the free tools
  (calculators, rules table, figures card, examples and the tools page) are
  counted per day, language, link tag (…) and page group (a short page name,
  never the full address or its parameters), with no address».
- pt: «as visitas à página inicial, às páginas de casos, aos guias, aos
  artigos, à revisão institucional, às páginas públicas de verificação e às
  ferramentas grátis (calculadoras, tabela de regras, cartão de números,
  exemplos e página de ferramentas) são contadas por dia, idioma, etiqueta do
  link (…) e grupo de página (um nome curto da página, nunca o endereço
  completo nem seus parâmetros), sem endereço de rede».

Al aplicarla, vaciar `LEGAL_TEXT_PENDING` en `tests/test_audit_page_visits.py`
moviendo cada entrada a `LEGAL_NAMES` (y la dimensión a una comprobación de
presencia). Hasta entonces la rama no debe ir sola a producción.
