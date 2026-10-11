# Codex 31 · Checklist para copiadores de señales

La página `/para/copiar-senales`, `/for/signal-copiers` y
`/pt/para/copiar-sinais` responde a la pregunta de búsqueda con un H2 literal,
siete comprobaciones numeradas, herramientas y un ejemplo. Conserva las
secciones de problemas, archivos, revisión, límites, precio y preguntas.
Las tres preguntas visibles alimentan el mismo `FAQPage`.

## Cifras y alcance

- `audience_numbers.py` calcula las cifras con `winrate`, `ruin_calc`,
  `calculator` y el parser y lector de `reading`/`public_card`. Las reglas
  de banderas se importan de `account` y `redflags`; no se añaden umbrales.
- Ejemplo hipotético DECLARED: 80 % de aciertos, 40 operaciones,
  +120 % en 6 meses, drawdown 12 %. Wilson al 95 %: 65,2 %–89,5 %.
- Escenario de tamaño separado, también DECLARED: cada operación gana 1 %
  o pierde 3 % del saldo inicial, con 500 operaciones y 4.000 trayectorias
  de semilla fija. La pérdida límite es 30 % del saldo inicial (no drawdown
  desde el máximo). La frecuencia simulada es 1,5 % con el acierto declarado
  y 100,0 % usando el extremo inferior de Wilson. Se muestran ambas.
  Esta comparación no es un intervalo de confianza para la ruina ni una
  probabilidad observada del proveedor. No se reconstruye el +120 %.
- Ejemplo de suerte independiente: Sharpe anual 1, 100 búsquedas, medio año.
  La calculadora da unos 78 meses (años calculados convertidos a meses y
  redondeados hacia arriba) para que el Sharpe esperado por suerte quede
  debajo del observado. Supone 252 retornos diarios por año, normales e
  independientes, y búsquedas independientes. No es un umbral de seguridad
  ni una probabilidad de Sharpe deflactado; el informe calcula esta última
  con los retornos.
- El modelo de ruina usa importes fijos, operaciones independientes y ningún
  costo adicional; no modela capitalización, martingala, gaps o dependencia
  entre pérdidas. Wilson también presupone independencia. Ningún ejemplo
  describe una cuenta real, aconseja copiar ni anticipa resultados.

## Limitaciones encontradas

El lector de esta rama no tiene campos de ganancia, drawdown o meses:
acepta `trades`, `win_rate`, `profit_factor`, `sharpe`, `years`, `trials`,
`target_r` y `stop_r`. Por ello no se pudo hacer una lectura directa de
«+120 % / 6 meses / 12 %» como se describía en el encargo. Se introducen
los seis meses como 0,5 años y se reproduce Wilson con 40 y 80 %. La suerte
queda `NOT_MEASURED` porque falta el número de búsquedas; tampoco se infiere
un Sharpe de ganancia/drawdown. La página explica esta limitación y pide
el historial para revisar depósitos, flotante y patrones de tamaño.

La pregunta completa en inglés más la marca supera los 65 caracteres del
control general de títulos; es la consulta literal de Search Console y se
conserva. `public_hygiene` mantiene ese control para todas las demás páginas
y exige el título exacto solo para `/for/signal-copiers`. Las preguntas en
español y portugués no son consultas reales: se acortaron («¿Cómo elijo un
proveedor de señales sin que me barran?», «Como escolher fornecedor de
sinais sem quebrar a conta?») para caber en el tope con la marca, y el H2 y
la meta description llevan la misma pregunta corta. Las meta descriptions
mantienen el límite de 160 caracteres.

Las traducciones nuevas son contenido editorial explícito es/en/pt, no
notas nuevas del motor de informes; no cambian las reglas de `i18n.py`.
Los enlaces de informe explican que el primero es gratis con cuenta; las
calculadoras, el lector y el ejemplo son gratuitos sin registro.

## Validación

Se usa `D:\wt\.venv-pp\Scripts\python.exe`, `PYTHONPATH` apuntando al `src`
de este worktree y directorios `bt-codex31-*` bajo el basetemp indicado.
El sandbox impide arrancar el Python base del entorno; la misma orden
funciona con ejecución escalada autorizada, sin cambiar el entorno.

- `audience_pages`, `landing_audiences`, `public_hygiene` con
  `-k 'signal_copiers or signal-copiers or copiar-senales or copiar-sinais or audience_texts or every_audience'`:
  62 correctos, 2.094 deseleccionados (`bt-codex31-22`).
- Los tres archivos completos, en una tanda: 2.156 correctos
  (`bt-codex31-31`). Incluye HTTP 200, enlaces, metadatos, jerarquía de
  encabezados, guard y JSON-LD.
- `guides_seo` y `audience_numbers`, completos: 26 correctos
  (`bt-codex31-32`). Los nueve tests de cifras también se ejecutaron por
  separado durante su implementación (`bt-codex31-101`).
- Las cifras se contrastan con el parser público y los motores de Wilson,
  ruina y suerte; el render se comprueba en los tres idiomas. Se exige
  `find_claims == []`, se comprueban las palabras excluidas y la coincidencia
  entre las tres FAQ visibles y `FAQPage`.
- `mypy --follow-imports=silent` sobre los cuatro módulos Python de
  producción modificados: sin errores. `ruff format --check` sobre los
  siete archivos Python modificados: correctos. Archivos en LF y
  `git diff --check` limpio.
- Advertencia existente de Starlette por `httpx` en TestClient; ninguna
  llamada de datos de mercado ni bróker en las pruebas.

Tras precisar la redacción de suerte, costos y banderas, la tanda enfocada
final (`bt-codex31-33`) termina con 62 correctos y 2.094 deseleccionados.
`ruff check .` sobre todo el repositorio, mypy y formato también terminan
sin errores.

Trabajo local en `feat/copiadores-checklist`, sin push ni PR. No se añaden
datos de clientes, cachés, conexiones a proveedores ni ejecución de operaciones.

## Revisión posterior (hallazgos aplicados)

- Los enlaces al lector y a la calculadora de ruina van prellenados con el
  ejemplo (`reading_url(locale, reader_values())` y
  `ruin_calc.share_url(locale, ruin_input)`), para que el visitante vea el
  intervalo Wilson y el gemelo al extremo inferior que la página describe;
  la comprobación 6 pide el acierto con sus operaciones, sin las cuales la
  calculadora no muestra ese gemelo. El test de enlaces abre ambos href y
  exige 200 y las cifras.
- Cifras nuevas, siempre calculadas: acierto de equilibrio con +1 %/−3 %
  (`winrate.read` con `target_r`/`stop_r`, 75,0 %), esperanza por operación
  al acierto declarado (+0,20 %) y al extremo inferior de Wilson (−0,39 %),
  tomadas de `RuinRun.expectancy_share`, y la fila de monedas justas del
  lector (`reader_rows`, clave `coin`), que sí se calcula con 40 operaciones.
  La fila que queda sin medir es el Sharpe esperado por suerte, por falta de
  configuraciones (sin Sharpe declarado el lector usa el modelo nulo).
- Los códigos de evidencia quedan solo en atributos: dentro de una frase
  `localize_text_nodes` los imprimía como «Declarado (Declarado)» o «queda No
  medido». El texto usa «declarado», «sin medir» / «unmeasured» / «sem medir».
- La comprobación 1 contrapone los 6 meses declarados a los 78 que calcula
  la calculadora de suerte; un test exige esa desigualdad.
- La comprobación 7 nombra la sección del ejemplo tal cual
  (`seller_message.COPY[locale]["title"]`: «Mensaje para el vendedor»,
  «Message for the seller», «Mensagem para o vendedor»).
