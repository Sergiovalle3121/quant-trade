# Codex 25 · Artículo sobre riesgo de ruina

Fecha editorial: 2026-10-11. Rama: `feat/articulo-ruina`.
Base local de las comprobaciones: `266f344`.

## Entrega

- Artículo en español, inglés y portugués, con los slugs solicitados.
- Tabla generada desde `article_numbers.RUIN_INPUTS` y `RUIN_READINGS`, calculados
  con `ruin_calc.compute`; cada celda conserva la etiqueta de evidencia declarada.
- Enlaces a las calculadoras de ruina, aciertos y reto, al artículo de rachas,
  a la subida y al informe de ejemplo. Fecha incluida en sitemap y JSON-LD.
- La tabla usa el contenedor desplazable existente, también accesible por teclado.

## Supuestos e interpretación

La tarea fija las relaciones en R pero no su escala respecto al balance. El ejemplo
declara **1R = 1 % del balance inicial**, fijo durante la trayectoria, sin recomendar
un tamaño de posición. En el motor, el umbral del 30 % significa **perder el 30 % del
balance inicial y tocar el 70 % restante**. No es un saldo restante del 30 % ni un
drawdown desde un máximo móvil. El horizonte es de 500 operaciones.

Los tres casos usan las muestras y la semilla del motor, sin modificarlo. El artículo
explica independencia, probabilidad constante, importes fijos, ausencia de reinversión
y costos no añadidos. Un cero observado en las trayectorias no significa que el
evento sea imposible. El escenario con Wilson inferior no constituye un intervalo
de confianza de la probabilidad de ruina ni cubre la incertidumbre de los importes.

La búsqueda con `winrate.read` distingue tres resultados calculados:

- 385 operaciones: primer entero que sitúa el límite inferior estrictamente por
  encima del equilibrio, manteniendo la proporción declarada en 55 %.
- 400 operaciones: primer tamaño que cumple la condición y permite exactamente
  55 % de aciertos con conteos enteros.
- 500 operaciones: primer tamaño de la cuadrícula que muestra la calculadora.

Son comparaciones a tasa constante, no una predicción al añadir nuevas operaciones.
Los tests recomputan los valores, revisan el cruce sin redondear y comprueban las
celdas localizadas contra ambos motores.

Se contrastó la interpretación del intervalo de Wilson con el
[manual de NIST](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm).
La fórmula clásica se contrastó con el material de
[MIT sobre la ruina del jugador](https://ocw.mit.edu/courses/6-042j-mathematics-for-computer-science-fall-2005/3b4935f73cef38f60e455acaddb5ec65_cp15wsol.pdf).
Las cifras publicadas proceden exclusivamente de las funciones del repositorio.

## Validación

Python: `D:\wt\.venv-pp\Scripts\python.exe`.
`PYTHONPATH=D:\wt\codex-25\src`. Ejecuciones por tandas de uno a tres archivos,
con `--basetemp` bajo la ruta temporal indicada en la tarea.

El aislamiento impide iniciar el Python base de ese entorno virtual; las mismas
órdenes se ejecutaron con elevación autorizada por la revisión automática.

Comprobaciones terminadas (2.333 pruebas correctas en las tandas completas):

- `articles_ruin`, `articles` y `guides_seo`: selección final con `-k`,
  7 correctas y 41 deseleccionadas (`bt-codex25-27`); tanda completa,
  48 correctas (`bt-codex25-25`).
- `ruin_calculator` y `public_hygiene`: selección con `-k`, 30 correctas y
  2.076 deseleccionadas (`bt-codex25-23`); tanda completa, 2.106 correctas
  (`bt-codex25-26`).
- `article_structured_data`, `articles_next_steps` y `articles_montecarlo_streaks`:
  selección `-k 'ruina or every or json or next_step or computed or table'`,
  124 correctas y 37 deseleccionadas (`bt-codex25-31`); tanda completa,
  161 correctas (`bt-codex25-32`).
- Compatibilidad adicional de `retail_articles`, con `-k 'article or guard'`:
  18 correctas, ninguna deseleccionada (`bt-codex25-33`).
- `mypy --follow-imports=silent` sobre los seis archivos Python modificados:
  sin incidencias. Incluye dos ajustes mínimos de tipos en tests existentes.
- `ruff check` y `ruff format --check` sobre esos seis archivos: correctos.
- `git diff --check`: correcto. Los siete archivos de la entrega usan LF.

Las tandas con `TestClient` muestran la advertencia existente de Starlette sobre
la integración con `httpx`; no impide ejecutar las comprobaciones.

## Pendientes

No queda trabajo solicitado pendiente. No se ha hecho push ni creado PR.
La única advertencia de las pruebas es la deprecación preexistente de Starlette
indicada arriba; no se cambiaron dependencias para este artículo.
