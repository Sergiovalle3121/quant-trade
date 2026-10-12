# Codex 39: lotes, contratos y caída al copiar

Trabajo en `feat/lotes-y-dinero`, sin envío remoto ni solicitud de integración.

El informe completo añade tamaño típico (mediana) y cantidad por límite de
pérdida en las unidades originales del archivo. Los importadores conservan
los volúmenes originales porque la cantidad interna puede incluir el valor
económico del contrato. Lotes en pasos de 0.01, contratos enteros, ambos hacia
abajo; las unidades desconocidas llevan dos decimales. Un resultado inferior
al mínimo lo dice expresamente. El tamaño variable lleva aviso y la
martingala detectada no recibe cantidad fija.

La tabla de copia calcula la caída de referencia sobre el balance inicial
con multiplicadores 0.5x, 1x, 2x y 3x; desde el 100 % muestra la pérdida de
la cuenta entera. Se declaran los supuestos de tamaños fijos, mismo balance
inicial y ausencia de cierres por margen. Un balance supuesto por el lector
del archivo no basta para medir cantidades ni porcentajes del proveedor.

El reto conserva su tabla previa y añade el máximo típico por pérdida diaria
en esas unidades. Usa cierres diarios UTC de una curva monetaria y la base
que define la regla de la firma; incluye el primer día desde el balance
inicial. El redondeo excluye la frontera exacta.
Depósitos o retiros que convierten la curva en un índice, y curvas sin
evidencia monetaria suficiente, impiden medir este máximo. No se incluyen
pérdidas intradía ni la restricción de pérdida total en esa cifra.

HTML y PDF comparten el mismo renderizado y textos es/en/pt. La vista previa,
precios, formulario, textos legales y privacidad no cambian. No se modifican
los veredictos ni se añaden operaciones reales o conexiones de ejecución.

Validación ejecutada con el Python del entorno `.venv-pp`, `PYTHONPATH=src`
y pytest en tandas de uno a tres archivos, con los directorios temporales
`bt-codex39-*` indicados para esta sesión:

- Capital y cantidades: 29 pruebas; importadores y unidades: 128 pruebas.
- Reto y escalera: 89 pruebas; tras cubrir la pérdida del primer día,
  se repitió `test_audit_challenge_sizing.py`: 66 pruebas.
- Integración de cantidades: 5 pruebas, incluidos flujos, balance supuesto,
  curva sin conciliar y detección real de martingala sin mocks.
- i18n, site_copy_trust y public_hygiene: 2.333 pruebas; las dos pruebas
  de reglas y guard se repitieron después de registrar los avisos de la UI.
- Renderizado nuevo: 33 pruebas; PDF y origen, junto con renderizado:
  43 pruebas antes de añadir los tres casos de paginación; portugués: 17.
- Motor, cifras del informe y procedencia de la documentación: 66 pruebas.
- Informe, presentación y vista previa anónima: 112 pruebas. El guard de
  procedencia se repitió sobre la documentación final: 20 pruebas.

Ruff check y format correctos en los 14 archivos Python modificados;
mypy `--follow-imports=silent` correcto en los nueve módulos modificados.
Los archivos mantienen LF y `git diff --check` no encuentra errores.

Se habilitó el runtime local de Pango mediante `WEASYPRINT_DLL_DIRECTORIES`
para ejecutar las pruebas PDF reales. Se generaron informes completos
sintéticos en es/en/pt, se rasterizaron sus páginas con Poppler y se revisaron
las cantidades y el reto. La tabla de copia mantiene título, supuesto y
cuatro filas en una misma página. Los PDF, HTML y PNG de revisión quedan en
`outputs/`, ignorados por Git; no contienen archivos de clientes.

Los avisos observados son de la dependencia Starlette/httpx y, en el primer
runtime PDF, de la configuración local de fuentes. No se omite la validación
PDF por falta de Pango. Los límites restantes son del método y se muestran
en el informe: escala lineal histórica, cierre diario UTC y ausencia de
simulación de margen o de la pérdida total dentro del máximo diario.
