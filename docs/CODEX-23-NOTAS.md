# Codex 23: artículo de consistencia

El artículo está implementado en español, inglés y portugués con fecha
2026-10-11. Las cifras proceden de `challenge_calc.compute` a través de
`article_numbers.py`; las reglas, fuentes y fechas proceden de `PRESETS`.

La comprobación global `python -m ruff format --check` devuelve un error:
84 archivos requieren formato y 802 ya tienen el formato esperado. Los 84
archivos señalados no forman parte de este cambio y no se han modificado;
incluyen código de backtesting, investigación y sus pruebas. Se conserva
su contenido para mantener el alcance del artículo.

`ruff check` global y el formato de los archivos modificados están correctos.
Mypy sobre `articles.py` y `article_numbers.py`, con
`--follow-imports=silent`, no encuentra errores. El contenido solicitado no
tiene otras excepciones.
