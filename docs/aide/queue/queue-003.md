# Queue 003 — Compresión 7z (Etapa 3 del roadmap)

> **Paso 4 del flujo AIDE.** Lote de ~10 work items priorizados desde `docs/aide/roadmap.md` y `docs/aide/progress.md`. Cubre la Etapa 3: compresión de cada `.fbk` a `.fbk.7z` con `py7zr`, nivel configurable, cifrado opcional y pipeline `respaldo → compresión` en `odin run`. Dimensión total: ~1 semana.
>
> **Agrupación de implementación:** los items se ejecutan en 3 lotes por afinidad de contexto (misma superficie de archivos). Cada lote se ejecuta en una sesión con `/speckit.aide.execute-batch <items>` (ver el comando exacto en cada lote), que crea los specs faltantes, implementa item por item y actualiza el progreso. La numeración de items no cambia.

---

## Lote A — Núcleo de compresión (`src/odin/compress.py`)

> Items 020, 021, 022, 023 y 027. Todos modifican el mismo módulo y sus tests: hacerlos en sesiones separadas obliga a releer y reescribir el mismo contexto. Los tests unitarios del Item 028 correspondientes a ida y vuelta, efecto del nivel y fallos de compresión se adelantan aquí; el test de integración y la demo quedan en el Lote C.
>
> **Comando:** `/speckit.aide.execute-batch 020-023,027`

### Item 020: Implementación core de `src/odin/compress.py` (`.fbk → .fbk.7z` con py7zr)
Implementar la lógica base de compresión con `py7zr`: recibir el `.fbk` de origen y la ruta destino `.fbk.7z`, comprimir con el nivel configurado y validar el artefacto resultante (existe, no vacío y legible), midiendo duración y tamaños original/comprimido. Definir el dataclass `CompressionResult` (éxito/fallo, rutas, tamaños, ratio, duración y mensaje de error) reutilizable por el pipeline. Los errores operativos esperados (origen inexistente/vacío, fallo de `py7zr`, permisos) no se propagan como excepción: se reportan en `CompressionResult`. Tests unitarios con archivos reales temporales.

### Item 021: Escritura atómica del `.7z` y manejo del destino existente
Comprimir a un archivo temporal en el mismo directorio y publicarlo con `os.replace` solo si la operación fue exitosa, eliminando el temporal ante cualquier fallo para no dejar `.7z` parciales huérfanos. Definir y documentar el comportamiento ante un destino ya existente (sobreescritura controlada según la convención de timestamp). Tests: fallo simulado a mitad de compresión (mock de `py7zr`) no deja residuos; un destino existente se maneja sin corromper el archivo previo.

### Item 022: Nivel de compresión configurable (`compression.level`) con efecto medible
Mapear `compression.level` (0–9, default 7) a los presets/filtros de `py7zr`, validando el rango en la fase de compresión además de en `config.py`. Tests que compriman datos sintéticos compresibles y verifiquen que nivel 1 y nivel 9 producen tamaños de salida distintos (efecto medible), y que el nivel efectivamente usado queda registrado en el log.

### Item 023: Cifrado AES-256 opcional con `compression.password`
Implementar el cifrado del `.7z` cuando `compression.password` está definido, usando el soporte 7zAES/AES-256 de `py7zr`. Verificar su estabilidad en la versión fijada y documentar la decisión (habilitado, o descartado con motivo) en docstring/README. La contraseña nunca debe aparecer en logs, mensajes de error ni resúmenes. Tests: el archivo cifrado solo se extrae con la contraseña correcta; contraseña incorrecta falla; los logs no contienen el secreto.

### Item 027: Logging y enmascarado de secretos en la fase de compresión
Integrar los logs de compresión con el sistema de logging de la Etapa 1: inicio/fin por base, tamaño original/comprimido, ratio, nivel, duración y si el artefacto está cifrado (sin exponer la contraseña). Asegurar que `compression.password` está cubierto por `iter_secret_fields()`/`SecretMasker` y los patrones de enmascarado existentes. Tests de ausencia del secreto en logs y en salidas de error.

---

## Lote B — Orquestación (`odin run`: respaldo → compresión)

> Items 024, 025 y 026. El Item 025 depende del 024 y el Item 026 refina el resumen que introduce el 025; conviene un único pase sobre `src/odin/backup.py` y `src/odin/cli.py`. Al extender `BackupResult` (hoy `frozen=True, slots=True` en `backup.py:68`), agregar los campos de compresión con defaults para no romper consumidores existentes.
>
> **Comando:** `/speckit.aide.execute-batch 024-026`

### Item 024: `CompressionExecutor` con lotes y aislamiento de fallos
Implementar un ejecutor que recorra los respaldos exitosos de un lote y comprima cada uno de forma secuencial, aislando fallos por base (una compresión fallida no interrumpe el resto) y reportando un resultado agregado (`BatchCompressionResult`, análogo a `BatchBackupResult`). Solo se comprimen `.fbk` validados; los respaldos fallidos se omiten. Tests con dobles/mocks de la función de compresión y de `py7zr` para casos de éxito, fallo y lote vacío.

### Item 025: Extensión de `BackupResult` y pipeline `odin run`: respaldo → compresión
Extender `BackupResult` con los datos de compresión (`archive_path`, `compressed_size_bytes`, `compression_duration_seconds`, error de compresión) y modificar `_cmd_run` para que, tras el lote de respaldo, comprima cada `.fbk` exitoso. Una base cuenta como exitosa solo si respaldo y compresión culminan bien; el lote mantiene el aislamiento de fallos. Tests de integración de la CLI con `gbak` mockeado y compresión real en un `work_dir` temporal.

### Item 026: Resumen de `odin run` y exit codes con archivos comprimidos
Actualizar el resumen de consola para informar por base la ruta del `.fbk`, la del `.fbk.7z`, tamaño original/comprimido y duración de cada fase, y ajustar la semántica de exit codes: 0 solo si todas las bases se respaldaron y comprimieron, 3 si hubo mezcla de éxitos y fallos, 4 si falló todo. Tests de la CLI para cada escenario, incluida compresión fallida con respaldo exitoso.

---

## Lote C — Verificación y cierre

> Items 028 y 029. Ejecutar recién con los Lotes A y B completos: test de integración marcado (`@pytest.mark.integration`), corrección del mensaje de `validate.py:607` que anuncia el cifrado como "Etapa 3" futura, documentación, `ruff`/`mypy` en verde y demo final de `odin run` con `.fbk` + `.fbk.7z`.
>
> **Comando:** `/speckit.aide.execute-batch 028,029`

### Item 028: Tests de ida y vuelta y de fallos de compresión
Consolidar la batería de la Etapa 3: ida y vuelta (comprimir con ODIN, extraer con `py7zr`, comparación byte a byte), origen inexistente/corrupto, fallo por disco lleno simulado (`OSError: No space left on device`), interrupción con limpieza de temporales, y test de integración marcado con `@pytest.mark.integration` que ejecute `odin run` (con `gbak` mockeado o Firebird real) y verifique la generación de ambos artefactos. Dejar `uv run pytest` verde.

### Item 029: Documentación de la compresión y limpieza de la Etapa 3
Actualizar `README.md` con la sección de compresión (nivel, cifrado opcional, nombres de archivo y comportamiento ante fallos) y corregir el mensaje de `validate.py` sobre `compression.password`, que hoy anuncia el cifrado como "Etapa 3" futura. Revisar consistencia de docstrings y módulos, y cerrar con `uv run pytest`, `ruff` y `mypy` en verde más una demo final de `odin run` mostrando `.fbk` + `.fbk.7z` con tamaños informados.

---

**Total: 10 items en 3 lotes.** Al completar este lote, la Etapa 3 del roadmap quedará cerrada y la Etapa 4 (transferencia SFTP) podrá comenzar. El siguiente lote (`queue-004.md`) arrancará en el item 030.
