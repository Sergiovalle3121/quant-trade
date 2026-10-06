# Validación del simulador privado: 2026-10-05

El bot es exclusivamente simulación privada. No conecta cuentas, no envía órdenes de broker y
`real_money_approved=false`. La observación prospectiva aún no comenzó: cero días nuevos,
`paper_90d_3rebals_complete=false`. Las mejoras del motor no demuestran una ventaja económica.

## Ensayo conservado

Se conserva un único replay de desarrollo, con código de reproducción `4c39e97`, desde
2020-04-03 hasta 2026-10-02, después del calentamiento. Son datos históricos conocidos:
**no constituyen una evaluación independiente**. Cada alternativa parte de 20,000 MXN simulados;
no se suman nueve capitales ni se interpreta el conjunto como una cartera financiada.

Los siguientes valores están expresados en MXN e incluyen FX y costos hipotéticos de trading.
No incluyen infraestructura no observada ni impuestos. El retorno es acumulado durante todo
el período, no anual. El drawdown corresponde a valoraciones al cierre, no al máximo intradía.

| Alternativa | Costos | Valor final simulado MXN | Retorno acumulado | Mayor caída al cierre |
|---|---:|---:|---:|---:|
| Inverso de volatilidad | 1× | 30,301.67 | 51.51% | 28.70% |
| Inverso de volatilidad | 2× | 30,209.94 | 51.05% | 28.70% |
| Inverso de volatilidad | 3× | 29,979.92 | 49.90% | 29.14% |
| Objetivo de volatilidad 10% | 1× | 22,549.52 | 12.75% | 25.79% |
| Objetivo de volatilidad 10% | 2× | 22,525.66 | 12.63% | 25.79% |
| Objetivo de volatilidad 10% | 3× | 22,501.80 | 12.51% | 25.78% |
| Control uniforme trimestral | 1× | 35,401.66 | 77.01% | 29.74% |
| Control uniforme trimestral | 2× | 35,307.91 | 76.54% | 29.72% |
| Control uniforme trimestral | 3× | 35,214.37 | 76.07% | 29.70% |

Ambas candidatas terminaron por debajo del control en valor final en los tres escenarios.
Las nueve alternativas terminaron pausadas por `daily_loss_limit`. La pausa frena compras y
conserva posiciones: no liquida automáticamente ni limita las pérdidas al umbral de 5%.
Se preservan las caídas, las pausas y los períodos sin operaciones.

El diario conservó 1,633 cierres valorados por alternativa, 14,697 valoraciones, 92 fills,
92 órdenes y 1,404 acciones corporativas. Respaldo, restauración y reinicio conservaron carteras,
conteos y pausas sin duplicados. La reproducción y esas verificaciones no se repitieron con
código nuevo para modificar los resultados anteriores.

## Procedencia y límites

- Código de reproducción completo: `4c39e972dfede1d0fe36f09e68ba1d4056f31a44`.
- Hash del código ejecutado: `bcb6a1f4cd616384bb87be7977f9951dfb7977634f64159ebbe7e0b9d99e4547`.
- Hash del protocolo económico: `027436a85b382b47562e127fb8fb7629b484cf9b1378df24a0c66a742fb7903c`.
- Hash del ledger histórico: `ddb7b5f5eef65afdc7db30a1efa51709bac58453bf3043869d096f6339b3ae30`.
- Fuente: snapshot privado Yahoo Finance/yfinance recibido el 2026-10-05; archivos y manifest
  se conservan fuera de Git. No se publican cache de mercado ni bases de datos.

El registro se creó mientras la reparación final estaba sin commit. Su metadata Git conserva
`b7dcad8`, mientras los hashes sellados corresponden al código publicado `4c39e97`. Se mantiene
esa diferencia explícita; no se reescribe el manifest antiguo.

La liquidez de desarrollo usa volumen de la sesión previa cerrada como proxy; no mide la
liquidez disponible en la apertura. Las fracciones y costos son supuestos. El dividendo se
acredita hipotéticamente en fecha ex, sin modelar la fecha de pago ni impuestos.

La selección ETF anterior conservó [cero de ocho candidatos seleccionados](real_data_evidence/selection_benchmark_aware/selection_summary.md).
Sus rechazos permanecen visibles y no se sustituyen con este replay.

La evaluación conservada es **INCONCLUSIVE**. La infraestructura está `UNOBSERVED`; un costo
ausente no equivale a cero. El ledger contiene 109 resultados, pero faltan los momentos de
combinaciones históricas en 48 grupos. El generador nuevo conserva todas las combinaciones;
no recupera retrospectivamente la evidencia ausente ni inventa estadísticas.

## Avances técnicos y siguiente evaluación

La [PR 424](https://github.com/Sergiovalle3121/quant-trade/pull/424) incorpora causalidad de datos,
precios de apertura observados para simulación, calendario XNYS, validación de FX/dividendos/splits,
límites de exposición/efectivo, pausas persistentes, escritor único y sumas estables al reiniciar.
La matriz privada del commit `d664953` aprobó 149 pruebas offline en Windows/Linux y Python
3.11/3.12. Cada cambio posterior requiere sus propios checks; esa aprobación no valida otro head.

Esta iteración corrige tres fallos operativos: gastos vacíos o fuera del mes ya no se muestran
como cero observado; el bloqueo por presupuesto publica estado atómicamente con fecha UTC;
los logs conservan causas de pausa y el aviso de simulación. Se aprobaron 162 pruebas locales
offline (159 del motor/worker/proveedor/economía/recuperación/seguridad y tres de CLI), Ruff,
formato y mypy sobre los doce módulos privados. CI incluye las pruebas nuevas en las cuatro
combinaciones de sistema operativo y Python. Los checks del head publicado deben concluir
antes de integrarlo; las pruebas de código no constituyen validación de resultados futuros.

Antes de observar datos nuevos se debe cerrar el CI actual, registrar una base prospectiva nueva
con reloj real, medir costos y preparar un programador privado. No hay un worker desplegado ni
un programador activado por esta entrega. El presupuesto adicional sigue limitado a 500 MXN/mes.

El control operativo exige al menos 90 días, 60 cierres nuevos y tres ciclos con fills por
candidata/escenario. La evaluación económica exige 252 intervalos nuevos entre cierres, costos
completos y comparación con el control: retorno positivo después de costos, diferencia de Sharpe
de al menos 0.10 y drawdown al menos 10% menor, con bootstrap y ajuste de múltiples ensayos.
La evidencia histórica incompleta puede mantener el resultado inconcluso aun con sesiones nuevas.
Ningún resultado activa órdenes reales; la elegibilidad y ejecución del broker siguen pendientes.

Las fusiones quedan a cargo de Claude Code. La integración del SaaS exige además comprobar
Railway, staging, respaldo/restauración y reversión antes de afectar el servicio público.
