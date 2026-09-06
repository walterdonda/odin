# Item 004: Logging con rotación y enmascarado de secretos

> **Work item — Paso 5 del flujo AIDE.** Origen: `docs/aide/queue/queue-001.md`, Item 004. Etapa 1 del roadmap.

---

## Descripción

Implementar `src/odin/log.py`: logging a consola y a archivo con rotación usando solo stdlib (`logging`, `logging.handlers`, `re`, `pathlib`). El destino del archivo de log es el directorio efectivo `local.resolved_log_dir` (propiedad del Item 002: `local.log_dir` o `<work_dir>/logs`), con formato que incluye timestamps y nivel configurable vía `local.log_level` (enum `LogLevel` del Item 002).

Incluir una utilidad de **enmascarado de secretos** reutilizable: recibe los valores sensibles obtenidos de `Config.iter_secret_fields()` (Item 002, docstring explícitamente preparado como insumo de este item) y los reemplaza por `***` en cualquier texto. Debe poder aplicarse como filtro del logger (consola y archivo) y quedar disponible para los correos de ejecución de la Etapa 5. Complementariamente, enmascarar bloques PEM de claves privadas (`-----BEGIN ... PRIVATE KEY----- ... -----END ...-----`) aunque su contenido exacto no esté en la lista de secretos (el contenido de claves nunca debe aparecer en logs, visión §6 Seguridad).

Este item no toca la CLI (Items 005–007): `setup_logging` se invoca con la configuración cargada; el cableado en `odin run`/`validate` llegará con esos items.

## Criterios de Aceptación

1. `setup_logging(config)` configura el logger `odin` con dos handlers: consola (`StreamHandler`) y archivo (`RotatingFileHandler` sobre `<resolved_log_dir>/odin.log`, codificación UTF-8); ambos con formato con timestamp (`%(asctime)s`), nivel y nombre del logger. Devuelve el logger configurado.
2. El nivel de ambos handlers y del logger proviene de `config.local.log_level` (enum `LogLevel` → `logging`).
3. El directorio de logs se crea si no existe (`mkdir(parents=True, exist_ok=True)`), incluyendo el caso por defecto `<work_dir>/logs`.
4. Rotación configurada con defaults sensatos y documentados (p. ej. 5 MiB por archivo, 5 backups); sin nuevas dependencias de terceros.
5. Re-invocar `setup_logging` no duplica handlers ni corrompe la configuración (idempotencia; necesaria para la recarga en caliente del modo servicio, Etapa 6).
6. Enmascarado: todo valor de `config.iter_secret_fields()` no vacío que aparezca en un mensaje de log se reemplaza por `***` en **ambos** destinos (consola y archivo). Bloques PEM de claves privadas se enmascaran también por patrón. Secretos vacíos se ignoran (enmascarar la cadena vacía destruiría el texto). El comportamiento con secretos muy cortos se decide y documenta en Decisions & Trade-offs.
7. La utilidad de enmascarado es pura e importable sin efectos secundarios (clase/funciones testables, sin tocar el logger global al importar), lista para reuso en la Etapa 5 (correos).
8. Tests unitarios (`tests/test_log.py`): enmascarado (secreto literal único y repetido, múltiples secretos, secreto vacío ignorado, bloque PEM, texto sin secretos intacto, integración con `iter_secret_fields` de un `Config` real de fixture) y configuración del logger (nivel, tipos de handlers, creación de directorio, mensaje escrito en archivo y consola, enmascarado en ambos destinos, idempotencia ante doble `setup_logging`).
9. Sin dependencias de terceros; `uv run pytest -q` verde; `uv run ruff check .`, `uv run ruff format --check .` y `uv run mypy` limpios.
10. Los tests existentes (Items 001–003) siguen pasando sin cambios de comportamiento.

## Pasos de Implementación

1. **`src/odin/log.py`** (solo stdlib):
   - Constantes: formato con timestamp (p. ej. `%(asctime)s | %(levelname)-8s | %(name)s | %(message)s`), nombre de archivo `odin.log`, `DEFAULT_MAX_BYTES` (5 MiB), `DEFAULT_BACKUP_COUNT` (5).
   - `SecretMasker`: colecciona secretos (valores no vacíos de `iter_secret_fields()`), con `SecretMasker.from_config(config)` como constructor principal y `mask(text) -> str` que reemplaza cada secreto literal por `***` (orden: de más largo a más corto para evitar solapamientos parciales) y luego aplica una regex para vaciar el cuerpo de bloques PEM `PRIVATE KEY`. Documentar la política de secretos cortos que se adopte.
   - `MaskingFilter(logging.Filter)`: aplica un `SecretMasker` al mensaje formateado del registro (cubriendo `record.getMessage()`, y args ya interpolados).
   - `setup_logging(config: Config) -> logging.Logger`: resuelve `config.local.resolved_log_dir`, crea el directorio, limpia handlers previos del logger `odin` (idempotencia), agrega `RotatingFileHandler(encoding="utf-8")` y `StreamHandler` con el formato y el filtro de enmascarado, fija el nivel según `config.local.log_level`, y devuelve el logger.
2. **Tests (`tests/test_log.py`):** según criterio de aceptación 8. Usar `tmp_path` para directorios de log, `capfd`/captura de stderr para consola, y los fixtures JSON existentes (`tests/fixtures/config_valid_linux.json`) cargados vía `load_config` para el `SecretMasker.from_config`. No dejar archivos de log fuera de `tmp_path`; limpiar el logger `odin` entre tests (fixture que remueva handlers) para evitar contaminación cruzada.
3. **Verificación de gates:** `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`.

## Estrategia de Testing

- Unit tests puros: sin servicios externos; `tmp_path` para el directorio de logs y fixtures JSON existentes para construir `Config` reales.
- El enmascarado se prueba como función pura (entrada → salida) y como filtro integrado en los handlers (el texto escrito en el archivo y en la consola no contiene el secreto).
- La idempotencia se prueba contando handlers tras dos llamadas a `setup_logging`.
- Gates: `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`.

## Dependencias

- **De items anteriores:** Item 002 (`config.py`: `LogLevel`, `LocalConfig.resolved_log_dir`, `Config.iter_secret_fields`, fixtures de test) — completado ✅. Item 003 (`paths.py`: `log_dir` ya normalizado en el modelo) — completado ✅.
- **Bloquea a:** Item 005/006 (CLI `validate`/`run` con logging activo), Etapa 5 (enmascarado reutilizado en correos, `notify.py`), Etapas 6/7 (logging persistente del servicio con rotación).

## Prerrequisitos de Testing

### Servicios Requeridos
- Ninguno: logging y enmascarado son lógica pura + stdlib.

### Configuración de Entorno
- Entorno del Item 001 operativo (`uv sync`). Sin variables de entorno ni secretos reales; los secretos de prueba salen de los fixtures JSON existentes.

### Checklist de Validación Manual
- [x] **Tests pasan:** `uv run pytest -q` verde (suite existente intacta + tests nuevos de `test_log.py`). 102 passed (2026-09-06).
- [x] **Lint/tipos:** `uv run ruff check . && uv run ruff format --check . && uv run mypy` sin errores (2026-09-06).
- [x] **Funcionalidad verificada:** ejecutar manualmente (vía `uv run python -c ...`) `setup_logging` con un `Config` de fixture: se crea `<resolved_log_dir>/odin.log`, un mensaje INFO queda escrito con timestamp, y un mensaje que contiene el password del fixture queda enmascarado (`***`) tanto en consola como en el archivo. Verificado el 2026-09-06 con `config_valid_linux.json`: `masterkey` → `***` en ambos destinos (2026-09-06).

### Resultados Esperados
- Archivos nuevos: `src/odin/log.py`, `tests/test_log.py`.
- Sin modificaciones a `config.py`/`paths.py` (se consume su API pública existente).
- ≥ 15 tests nuevos pasando; suite de los Items 001–003 intacta.
- Ninguna dependencia nueva en `pyproject.toml`.

## Decisions & Trade-offs

1. **Política de secretos cortos (`MIN_SECRET_LENGTH = 4`):** los literales de 1–3 caracteres de `iter_secret_fields()` se ignoran. Enmascarar literales tan cortos (p. ej. `a` o `7`) destruiría la legibilidad del log por falsos positivos sin beneficio real: una credencial así de corta es débil y debe corregirse en la configuración, no ocultarse en el log. Trade-off: un secreto real de 3 caracteres quedaría expuesto; se considera aceptable y la política está documentada en el docstring del módulo.
2. **Enmascarado literal con `str.replace`, no regex:** los secretos son valores arbitrarios del JSON; usar `re.escape`/regex agregaría complejidad y riesgo sin ganancia. El orden de más largo a más corto evita solapamientos parciales (`abcdef` antes que `abc`).
3. **PEM en un solo pase con alternativa `(-----END \2-----|\Z)`:** una primera implementación usaba dos regex separadas (bloque completo y luego bloque abierto); la segunda pasada reencontraba el marcador `BEGIN` de bloques ya enmascarados y devoraba también el `-----END-----`, rompiendo 2 tests heredados del commit previo. La regex única con backreference `\2` (el `END` debe coincidir con la etiqueta del `BEGIN`: `OPENSSH`, `ENCRYPTED`, `RSA`, …) preserva los marcadores y vacía solo el cuerpo; un bloque truncado sin `END` se enmascara hasta el fin del texto (postura conservadora: tras un `BEGIN` no hay forma de saber dónde termina el material de la clave).
4. **`MaskingFilter` por handler sobre el mensaje interpolado:** el filtro se aplica a `record.getMessage()` (con args `%` ya interpolados) y luego `record.args = None`, cubriendo tanto mensajes literales como formateados en ambos destinos. Alternativa descartada: enmascarar solo `record.msg` (dejaría secretos pasados como args).
5. **Idempotencia de `setup_logging`:** re-invocarla cierra y remueve los handlers previos del logger `odin` antes de crear los nuevos, y fija `propagate = False` para evitar líneas duplicadas si otro componente configura el root logger. Necesario para la recarga en caliente del modo servicio (Etapa 6).
6. **Defaults de rotación como constantes, no configurables en el JSON:** 5 MiB por archivo × 5 backups (`DEFAULT_MAX_BYTES`, `DEFAULT_BACKUP_COUNT`). Mantienen acotado el disco (~30 MiB máx.) sin sumar superficie de configuración en la Etapa 1; si la operación lo pide, exponerlos en `local` es un cambio retrocompatible.
7. **Correcciones sobre lo ya commiteado:** la sesión anterior había commiteado `log.py`/`test_log.py` con los 2 tests PEM fallando y 3 hallazgos de ruff (orden de imports, 2 líneas > 100). Se corrigió la regex PEM (decisión 3), se reordenaron imports y se aplicó `ruff format`. Sin cambios de API ni de comportamiento especificado.

## Recordatorio de Completado

> **IMPORTANTE:** al completar este item, actualizar `docs/aide/progress.md`: el entregable "Logging base: consola + archivo con rotación, nivel configurable, enmascarado de secretos" de la Etapa 1 debe pasar de 📋 → 🚧 → ✅, y actualizar la línea de "Última actualización". Este paso es parte de `/speckit.aide.execute-item`.

## Próximo Paso

Al completar, iniciar una **nueva sesión de chat** y ejecutar `/speckit.aide.create-item` con el número **005** (CLI con argparse, subcomandos y exit codes), luego `/speckit.aide.execute-item`.
