# Indicador Rigor para TradingView

Archivo: [`tools/tradingview/rigor_luck_sharpe.pine`](../tools/tradingview/rigor_luck_sharpe.pine), Pine Script v5. Es una tabla de investigación con tres entradas declaradas; no lee precios, operaciones ni archivos. No contiene señales, órdenes, alertas ni conexiones a intermediarios. Este cambio entrega el archivo; Sergio lo publica desde su cuenta.

## Uso y límites

Introduce el Sharpe anual del backtest, los años de historial y el total de configuraciones probadas, incluidas las descartadas. Los límites coinciden con `calculator.py`: Sharpe entre 0.05 y 10, años entre 0.1 y 50, configuraciones enteras entre 1 y 10,000,000. Las entradas y las cifras derivadas muestran `DECLARED`, nunca evidencia de un archivo.

Elige un gráfico diario, semanal o mensual de una sola barra por periodo: se suponen respectivamente 252, 52 o 12 periodos por año (`DECLARED`). Los gráficos intradía o con múltiplos de esos periodos muestran `NOT_MEASURED`; no se transforma su frecuencia de forma silenciosa. La frecuencia del gráfico debe corresponder a la serie del backtest declarado. No se estima la duración a partir de las barras cargadas.

El cálculo reproduce el máximo esperado de normales independientes y el descuento de Bonferroni de `calculator.compute`, con asimetría cero y curtosis tres. Usa la misma varianza de muestreo, inversa normal de Acklam y redondeo de observaciones con empates al entero par. Pine aproxima la cola normal directamente, para conservar probabilidades pequeñas; Python utiliza `erfc`. Los tests contrastan las expresiones matemáticas del propio archivo con Python y tolerancia absoluta de 0.00001 antes de redondear; la tabla muestra dos decimales. Eso no sustituye una compilación en TradingView.

Al igual que la calculadora, con menos de 20 observaciones o 28 días de historial el descuento no se calcula. Con una sola configuración no hay búsqueda que descontar: las dos casillas quedan en `NOT_MEASURED` y se explica el motivo. No se resta simplemente el Sharpe de suerte al Sharpe declarado.

Las colas gruesas, la asimetría, la dependencia entre configuraciones y una cuenta incompleta de las pruebas cambian la interpretación. No se miden costos, datos fuera de muestra ni calidad de archivos. La tabla describe supuestos sobre cifras declaradas; no asigna una clase ni describe resultados futuros.

## Comprobación manual antes de publicar

Estos mismos casos están en comentarios `PARITY` del Pine y se recalculan en `tests/test_tradingview_indicator.py`. Todas las entradas y salidas de la tabla son `DECLARED`.

| Gráfico | Sharpe anual | Años | Configuraciones | Periodos/año | Sharpe de suerte | Sharpe tras descuento |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Diario | 1.8 | 3 | 100 | 252 | 1.47 | 0.76 |
| Semanal | 1.0 | 2 | 1000 | 52 | 2.32 | 0.00 |
| Mensual | 2.5 | 5 | 10 | 12 | 0.80 | 2.26 |

Prueba también una sola configuración, un historial mensual demasiado corto y un gráfico intradía: deben aparecer los mensajes anteriores. Comprueba que el pie se lea completo. El texto fijo es: “Cifras declaradas · no es una auditoría · rigorscore.com/calculator?ref=tv”.

## Publicación desde la cuenta de Sergio

1. Abre un gráfico en TradingView y el Pine Editor. Crea un indicador vacío y pega el archivo completo, conservando `//@version=5`.
2. Guarda el script y añádelo al gráfico. Comprueba que compile y que los tres casos anteriores coincidan. El repositorio no incluye un compilador Pine.
3. Con el script abierto y añadido al gráfico, utiliza “Publish indicator/strategy/library”. Revisa primero una publicación privada, incluida la legibilidad de la tabla y la descripción. El flujo está descrito en la [documentación oficial de publicación](https://www.tradingview.com/pine-script-docs/writing/publishing/).
4. Para compartirlo, crea una publicación pública con código abierto y completa el título, descripción y etiquetas de abajo. Revisa las opciones y las normas de publicación que muestre TradingView en ese momento. Sergio realiza este paso; los tests no publican nada.

Título en inglés:

```text
Rigor - Luck and Sharpe from Declared Backtest Figures
```

Descripción en inglés:

```text
A research table for three declared inputs: annual backtest Sharpe, years of history, and configurations tried.

The table displays the expected maximum Sharpe of independent normal trials and the Sharpe left after a Bonferroni haircut. All inputs and derived figures carry DECLARED evidence labels. No prices, trade history, or files are measured.

Use a single daily, weekly, or monthly chart matching the backtest return frequency. The model assumes normal returns, independent configurations, and the displayed annual frequency. Unsupported chart intervals and insufficient history show NOT_MEASURED. One configuration has no search to discount.

This is an educational approximation of declared history, not an audit or a forecast. It does not assign a class or assess costs, out-of-sample evidence, or data quality. There are no signals, orders, or alerts. Source and calculation examples are included in the script.
```

Etiquetas en inglés (elige las equivalentes disponibles en el formulario):

```text
Statistics, Sharpe Ratio, Backtesting, Research, Education
```

La descripción está redactada para acompañar el indicador; el sitio aparece únicamente en el pie solicitado. Título, descripción, etiquetas, documentación y literales visibles del Pine pasan `quant_trade.audit.guard.find_claims` en el test offline.

## Tests locales

```powershell
& D:\quant-trade\.venv\Scripts\python.exe -m pytest tests/test_tradingview_indicator.py --basetemp D:\wt\lectura-publica\.pytest-tv --ignore-glob='tests/test_audit_pdf*.py' --ignore-glob='tests/test_personal_paper*.py' -q
```

La prueba evalúa únicamente las funciones aritméticas del archivo con una adaptación de sintaxis a Python y contrasta sus resultados con `calculator.compute`. No valida el compilador, la interfaz de TradingView ni su publicación. Los grupos PDF y personal-paper se excluyen conforme al brief.
