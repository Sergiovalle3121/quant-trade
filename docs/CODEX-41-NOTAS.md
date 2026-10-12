# Codex 41 · Mercados de tarjeta: Unión Europea y Reino Unido

Fecha: 2026-10-11. Rama: `feat/mercados-ue-reino-unido`.
Base local: `6aa738e`.

## Alcance

Se implementa la lista autorizada por Sergio en esta tarea: MX, US, BR, los
27 miembros de la Unión Europea y GB. La lista suma 31 países; la referencia
a 30 en el encargo era un error de conteo. Grecia usa GR y Reino Unido GB;
los alias EL y UK se rechazan, igual que cualquier país no revisado.

`audit/card_markets.py` centraliza los mercados revisados, los nombres en
español, inglés y portugués, y el orden de los selectores. Los países
habilitados siguen dependiendo de `AUDIT_APPROVED_MARKETS`, vacío por defecto.
La frase pública agrupa la Unión Europea solo si están habilitados todos sus
miembros; con una lista parcial muestra sus países y siempre nombra GB aparte.
Los selectores conservan MX, US y BR al principio y ordenan los demás por
nombre en el idioma de la página, ignorando mayúsculas y acentos.

La entrega conserva la comprobación del país declarado frente al facturado
por Stripe y su pertenencia a los mercados habilitados. Un cargo que no
cumple queda en `paid_review`, sin entrega. No cambia el precio, la moneda
USD, los impuestos, los textos legales, la privacidad ni los reembolsos.

## Despliegue y límites

El valor de producción se cambia después de desplegar. Esta tarea prepara
el código; no despliega ni modifica la configuración de producción.
No se consulta ni se cobra a Stripe: las pruebas usan sesiones simuladas
y webhooks firmados localmente. No se añaden conexiones de trading.

## Validación

El Python solicitado no puede arrancar dentro del sandbox; se usa el mismo
intérprete con permiso ampliado para ejecutar las comprobaciones.

Intérprete: `D:\wt\.venv-pp\Scripts\python.exe`.
`PYTHONPATH=D:\wt\codex-41\src`.
Pytest se ejecutó de forma secuencial, en tandas de uno o dos archivos, con
`-q --basetemp` y directorios creados antes de cada tanda bajo
`C:\Users\sergi\AppData\Local\Temp\claude\D--\f4a2342f-53ff-4bfb-827f-510fa2ff40a8\scratchpad\bt-codex41-<n>`.

| Tanda | Archivos en `tests/` | Resultado |
|---|---|---|
| 1 | `test_audit_settings.py`, `test_audit_card_payments.py` | 72 pasan |
| 2 | `test_audit_card_markets_line.py`, `test_audit_market_selectors.py` | 20 pasan |
| 3 | `test_audit_card_check.py`, `test_audit_account_credit_purchase.py` | 34 pasan |
| 4 | `test_audit_faq.py`, `test_audit_checkout_language.py` | 45 pasan |
| 5 | `test_audit_email_delivery.py`, `test_audit_pricing.py` | 47 pasan |
| 6 | `test_audit_oferta_pago.py`, `test_audit_i18n.py` | 60 pasan |
| 7 | `test_audit_site_copy_trust.py`, `test_audit_public_hygiene.py` | 2306 pasan |
| 8 | `test_provenance_guard.py` | 20 pasan |

Total: 2604 pruebas pasan. `test_audit_pricing.py` es el único archivo que
coincide con `test_audit_pricing*.py` en esta base. Las tandas web emiten
un aviso de deprecación de Starlette sobre httpx; no hay fallos de pytest.

La cobertura nueva incluye los 31 países en settings, rechazo de UK/EL/CA,
UE completa y parcial (también con un solo miembro ausente), GB aparte,
artículos y nombres en ES/EN/PT, y ambos selectores con catálogo completo y
subconjunto. Los pagos de informes y créditos usan webhooks HMAC simulados
para MX/DE/FR/GB, además de país no habilitado, país distinto al declarado
y retirada de habilitación antes del pago. Las frases y las páginas cumplen
`guard.find_claims == []`; no se añade el prefijo de evidencia a la prosa.

- `ruff check .`: sin errores.
- `ruff format --check` sobre los 11 archivos Python modificados: sin cambios.
- `mypy --follow-imports=silent` sobre los seis módulos modificados: sin errores.
- `mypy --follow-imports=silent --platform linux src`: sin errores en 447 archivos.
- `git diff --check` y revisión de saltos LF: sin incidencias.

### Límite de mypy en Windows

`mypy --follow-imports=silent src` informa cuatro errores `attr-defined`
preexistentes en `audit/pdf_tables.py:167-168`: `resource.setrlimit`,
`resource.RLIMIT_AS` y `resource.RLIMIT_CPU` no figuran para el destino Windows.
Ese archivo es idéntico al de HEAD al iniciar la tarea; los mismos errores
constan en `docs/CODEX-30-NOTAS.md` y `docs/CODEX-37-NOTAS.md`.
No se modifica ese código ajeno al alcance. La comprobación de todo `src`
con destino Linux y la de los módulos cambiados en Windows sí terminan sin errores.

No se ejecuta despliegue, cambio de entorno, push ni PR.
