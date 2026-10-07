# Evidencia de las versiones de una estrategia

La tabla privada conserva la procedencia del Sharpe, Sharpe deflactado y drawdown
de cada informe, tanto en HTML como en el resumen imprimible usado para PDF.
Una cifra declarada válida permanece visible como `DECLARED`; no se presenta
como calculada por el auditor. Una etiqueta desconocida, valor no finito,
booleano o desbordamiento produce un marcador `NOT_MEASURED`, sin inventar cero.

La API `headline` conserva sus tres claves y valores numéricos o `None`. La
presentación obtiene las etiquetas mediante `headline_evidence`, sin modificar
los informes almacenados, clases, créditos, permisos ni métodos estadísticos.

El texto «mejor» o «peor» del Sharpe exige cifras y extremos de las bandas
`MEASURED`, finitos y ordenados. También exige fechas completas con zona horaria,
duración positiva, frecuencia positiva disponible y tipos de curva explícitos
compatibles. Las horas equivalentes con offsets distintos siguen siendo válidas.
La frecuencia etiquetada debe ser coherente entre informes; si faltan etiquetas,
se conserva la tolerancia numérica existente del 10%. Un campo numérico sin
etiqueta del formato antiguo se admite como frecuencia positiva; una frecuencia
declarada o sin valor medido en un bloque de evidencia no completa ese contexto.

Se preservan las reglas de evolución existentes: al menos 80% de fechas comunes
respecto del historial más corto y bandas del bootstrap entre percentiles 5 y 95
que no se toquen. No se sustituyen por los criterios más estrictos del comparador
de diferencias aritméticas. Sin contexto suficiente o con bandas ausentes,
declaradas, inválidas o invertidas, el resultado es «sin cambio claro».

Estas etiquetas describen evidencia del historial aportado. El contraste de
bandas continúa siendo una regla descriptiva existente: no añade una prueba de
significancia de la diferencia, no demuestra una ventaja futura y no sustituye
una evaluación independiente con todos los ensayos registrados.

Las pruebas reproducen ausencia de fechas/frecuencia, mezcla de fechas sin zona,
equity frente a balance cerrado, declaraciones sin evidencia medida, contenedores
malformados y números que desbordan. Incluyen controles válidos, los límites
80%/10%, bandas que se tocan, ES/EN/PT y la misma tabla imprimible. No acceden a
datos de clientes, red ni brokers.
