# Codex 28 · Drawdown estático, EOD e intradía

Fecha editorial: 2026-10-11. Rama: `feat/articulo-trailing`.

## Entrega

- Artículo en español, inglés y portugués, con los slugs solicitados, metadatos,
  datos estructurados y fecha del sitemap.
- Nueve ejemplos: tres de cada tipo compatible con el simulador. Firma,
  programa, límite, fuente y fecha salen de `PRESETS`; no se cambian las reglas.
- Tres escenarios con las mismas entradas declaradas: 50 % de aciertos,
  ganancia de 1,5 R, pérdida de 1 R, riesgo del 0,5 % y tres operaciones al día.
  `article_numbers.py` obtiene los resultados de `challenge_calc.compute`;
  la tabla separa objetivo, límite total, límite diario y trayectorias sin terminar.
- Enlaces a los filtros `?perdida=static`, `?perdida=trailing_eod` y
  `?perdida=trailing_eod_lock`, calculadora, audiencia de retos y los artículos
  de consistencia y ruina, presentes en esta rama.
- Notas del catálogo citadas con sus traducciones existentes, fuente y fecha.
  Tablas con desplazamiento horizontal accesible y primera columna fija.
- Acortada la descripción española del índice: la prueba de Monte Carlo
  detectó que el texto previo tenía 159 caracteres frente a su máximo de 155.

## Límite del encargo que los datos no permiten cubrir

No se pueden dar dos o tres programas de trailing intradía con cifra y fuente
extraídos de `PRESETS`: el catálogo solo contiene los tres tipos simulables.
La nota de MyFundedFutures Rapid 50K menciona trailing del máximo intradía
en **Sim Funded**, mientras que la fila del catálogo representa la evaluación
EOD. No se atribuye a esa otra etapa el importe de pérdida de la evaluación.
El artículo explica la ausencia y deja su probabilidad intradía como
`NOT_MEASURED`; no se inventan programas, importes ni un filtro incompatible.

## Supuestos y limitaciones

Las cifras son `DECLARED`, nunca mediciones de un archivo. La historia sintética
parte de operaciones binomiales independientes; las trayectorias remuestrean
bloques de días, con las semillas, muestras y horizonte del cálculo existente.
Se suman retornos dentro del día y se capitaliza entre cierres. No se incluyen
costos, flotante ni incertidumbre del porcentaje de aciertos por tamaño muestral.

Los tres programas también difieren en objetivo, distancia de pérdida, días
mínimos y otras reglas: la comparación no aísla el efecto causal del trailing.
Alcanzar el objetivo es distinto de cumplir la regla del mejor día. El motor
comprueba primero el límite diario, después el total y luego el objetivo;
detiene cada trayectoria en su primer desenlace. Cuenta cierres estrictamente
por debajo del suelo, con tolerancia numérica, y no cualquier toque intradía.

Se distingue actualizar el suelo al cierre de vigilarlo durante la sesión.
Un historial con flotante y marcas temporales conserva más información, pero
solo a su resolución registrada. El simulador actual lo reduce a cierres
diarios. No se modifican motores, umbrales, proveedores ni rutas de ejecución.

## Validación

Python: `D:\wt\.venv-pp\Scripts\python.exe` con
`PYTHONPATH=D:\wt\codex-28\src`. El aislamiento impedía iniciar el intérprete
base; la ejecución con acceso ampliado funcionó sin modificar el entorno.
Cada tanda utilizó un directorio nuevo `bt-codex28-*` bajo el `scratchpad`
indicado en el encargo. Las pruebas usan datos locales y `TestClient`.

Resultados finales, en tandas de uno a tres archivos:

| Tanda completa, sin `-k` | Resultado |
| --- | --- |
| `articles`, `article_structured_data`, `articles_next_steps` | 137 correctos |
| `guides_seo`, `public_hygiene` | 2214 correctos |
| `articles_trailing`, `articles_consistency`, `articles_ruin` | 46 correctos |
| `articles_montecarlo_streaks` | 47 correctos |

Total de las tandas completas finales: **2444 pruebas correctas**. Los nombres
abreviados corresponden a `tests/test_audit_<nombre>.py`.

También se ejecutaron selecciones con `-k`: artículo nuevo (16 correctos),
artículos/datos estructurados/siguientes pasos (69 correctos), SEO/higiene
(31 correctos) e índice/descripción tras el ajuste de longitud (8 correctos).
La prueba nueva compara las cifras recalculadas y las reglas del catálogo,
comprueba HTTP 200, enlaces, idioma, metadatos, fechas y ausencia de expresiones
prohibidas; `guard.find_claims` devuelve `[]` en los tres idiomas.

`mypy --follow-imports=silent` sin errores en los cuatro módulos modificados;
`ruff check` y `ruff format --check` correctos en los siete archivos Python.
`git diff --check` correcto y ningún CR en los ocho archivos entregados.
Único aviso de pytest: deprecación preexistente de Starlette al usar httpx.

No se hace push ni se crea PR. Se deja el trabajo en commits locales.

## Revisión posterior (mismo día)

- La columna «Límite diario al cierre» imprime «Sin regla diaria simulada» cuando
  el preset no tiene `max_daily_loss` (Topstep); antes mostraba un 0,00 %
  declarado para una regla que el simulador no modela. La nota de la tabla
  añade, con cifras derivadas de las entradas y de `PRESETS`, que la peor
  jornada posible (3 pérdidas de 0,5 %) queda por debajo del límite diario más
  bajo (3 %), así que esa columna no puede activarse con estas entradas.
- Las notas de las dos tablas salen del `<caption>` a un párrafo anterior al
  contenedor desplazable: a 375 px el caption medía lo mismo que la tabla
  (472 y 666 px) y solo se leía desplazando.
- Las citas del catálogo llevan URL sin punto de corte; `theme.py` añade
  `overflow-wrap:anywhere` a sus párrafos y pies. Medido a 375 px: el ancho de
  desplazamiento pasa de 472 a 375 px en los tres idiomas.
- El horizonte del párrafo de supuestos se lee por programa (máximo de los
  tres, «hasta»), no solo del primero; la prueba comprueba que coinciden.
- Un párrafo generado desde `rules_table.loss_names` enlaza «estático»,
  «trailing EOD» y «con fijación» con los rótulos de la tabla y del filtro
  («fija», «sigue al mayor cierre diario», …).
- La introducción de las notas citadas aclara que «el artículo» y «el resumen»
  de la nota de E8 son páginas de la firma enlazadas en la propia nota.
- La respuesta de la FAQ dice «queda sin medir aquí» en lugar de incrustar el
  código `NOT_MEASURED` a mitad de frase.
- Se retira la cita de Earn2Trade, idéntica a la de Take Profit Trader salvo la
  URL y de un programa ausente en la tabla de reglas.
