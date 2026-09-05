# Item 002: Modelos de configuración y parseo del JSON

> **Work item — Paso 5 del flujo AIDE.** Origen: `docs/aide/queue/queue-001.md`, Item 002. Etapa 1 del roadmap.
>
> **Énfasis del solicitante:** el esquema debe dejar cubierta la detección y el logging de problemas del respaldo (disco lleno, fallos del proceso Firebird, corrupción del `.fdb`) y la verbosidad necesaria para informar por correo al equipo de DevOps. Esos mecanismos de runtime se implementan en la Etapa 2 (módulo de respaldo); este item garantiza que el **contrato de configuración** los soporte.

---

## Descripción

Implementar `src/odin/config.py`: modelos tipados del contrato de configuración JSON (visión §5) usando **solo stdlib** (`json`, `dataclasses`, `pathlib`, `enum`, `zoneinfo`), con carga, validación exhaustiva y **reporte agregado de errores** (todos los problemas de una vez, con ruta de campo y mensaje legible). El módulo es la base de `odin validate` (Item 006) y de todas las etapas posteriores.

El contrato de la visión se **extiende con campos opcionales retrocompatibles** orientados a confiabilidad/observabilidad (ver tabla de requisitos embebidos). Campos ausentes toman defaults seguros; campos desconocidos son error (detecta typos como `pasword`).

### Requisitos embebidos de detección de errores (provenientes del solicitante)

| Problema a detectar (runtime, Etapa 2+) | Soporte en el esquema (este item) |
|---|---|
| Disco lleno durante el respaldo | `local.min_free_mb` (umbral de preflight sobre `work_dir`) y `local.work_dir` tipado/validado |
| Problemas del proceso Firebird (gbak colgado/crash) | `local.gbak_timeout_sec` (default global) + override por base `databases[].gbak_timeout_sec` |
| Corrupción del `.fdb` | El esquema no lo resuelve, pero la verbosidad sí: `local.log_level` (DEBUG/INFO/WARNING/ERROR) y `notification.log_tail_lines` (líneas de log a incluir en el correo) permiten capturar y enviar la salida completa de gbak |
| Fallos transitorios de red SFTP | `local.sftp_retries`, `local.sftp_connect_timeout_sec` |
| Informar a DevOps por correo | `notification.to`/`from`/`smtp` validados + `notification.log_tail_lines` |

Extensión completa del esquema (nuevos campos opcionales sobre el contrato de la visión):

- `local.log_level`: `"DEBUG"|"INFO"|"WARNING"|"ERROR"` (default `"INFO"`).
- `local.log_dir`: ruta opcional (default `<work_dir>/logs`).
- `local.min_free_mb`: int ≥ 0 (default `1024`).
- `local.gbak_timeout_sec`: int > 0 (default `7200`).
- `local.sftp_retries`: int ≥ 0 (default `3`).
- `local.sftp_connect_timeout_sec`: int > 0 (default `30`).
- `databases[].gbak_timeout_sec`: override opcional del default global.
- `servers[].host_key_policy`: `"strict"|"known_hosts"|"accept-new"|"insecure"` (default `"strict"`).
- `notification.log_tail_lines`: int ≥ 0 (default `50`).

## Criterios de Aceptación

1. Un JSON conforme al contrato de la visión (ejemplos Linux y Windows, charset `ISO8859_1`) parsea a un `Config` tipado e inmutable, con defaults aplicados.
2. La validación reporta **todos** los problemas de una vez (`ConfigError.problems`), cada uno con `field_path` (p. ej. `servers[0].auth.password`) y mensaje claro; el mensaje incluye la ubicación del JSON fuente cuando aplica.
3. JSON malformado (sintaxis) produce error con línea/columna del archivo.
4. Reglas implementadas y testeadas: tipos y rangos (`compression.level` 0–9, `port` 1–65535, timeouts > 0, `retention_days` ≥ 0, `min_free_mb` ≥ 0); enums (`log_level`, `host_key_policy`, `auth.method`, `on_misfire`); campos requeridos por sección; coherencia `auth.method` ↔ `password`/`private_key`; nombres únicos de bases y servidores; `scheduler.jobs[].databases` referencia bases existentes; `schedule` con 5 campos; `notification.to`/`from` con formato de email básico; `timezone` válido vía `zoneinfo`.
5. **Campos desconocidos son error**, con sugerencia del campo más cercano (difusión de typo ≤ 2).
6. Rutas relativas se resuelven respecto de la ubicación del archivo JSON (normalización completa `/`/`\`/`~` llega en el Item 003; aquí `pathlib` básico).
7. Sin dependencias de terceros en el módulo (solo stdlib); `uv run pytest -q` verde; `ruff` y `mypy --strict` limpios.

## Pasos de Implementación

1. **Modelos (dataclasses `kw_only=True`, `slots=True`, frozen):**
   - `DatabaseConfig`: `name`, `connection`, `user`, `password`, `role: str | None`, `charset: str | None` (None = no pasar flag a gbak; decisión documentada), `gbak_path: str | None`, `gbak_timeout_sec: int | None`.
   - `ServerAuth`: `method: AuthMethod` (`PASSWORD`/`KEY`), `password: str | None`, `private_key: str | None`, `passphrase: str | None`.
   - `ServerConfig`: `name`, `host`, `port`, `username`, `auth: ServerAuth`, `remote_path`, `host_key_policy: HostKeyPolicy` (default `STRICT`).
   - `SmtpConfig`: `host`, `port`, `starttls: bool` (default True), `username`, `password`.
   - `NotificationConfig`: `to`, `from_` (mapeado del JSON `from`), `smtp: SmtpConfig`, `log_tail_lines: int` (default 50).
   - `CompressionConfig`: `level: int` (default 7), `password: str | None`.
   - `LocalConfig`: `work_dir: Path`, `retention_days: int`, `log_level: LogLevel` (default INFO), `log_dir: Path | None`, `min_free_mb: int` (default 1024), `gbak_timeout_sec: int` (default 7200), `sftp_retries: int` (default 3), `sftp_connect_timeout_sec: int` (default 30).
   - `SchedulerJob`: `databases: list[str]`, `schedule: str`, `on_misfire: MisfirePolicy` (default `RUN_ONCE`), `skip_if_running: bool` (default True).
   - `SchedulerConfig`: `enabled: bool` (default False), `timezone: str` (default UTC), `jobs: list[SchedulerJob]`.
   - `Config`: las seis secciones + helper `config_path` (ruta del JSON cargado).
2. **Errores:** `ConfigProblem(field_path: str, message: str)` y `ConfigError(Exception)` con `.problems: list[ConfigProblem]` y `__str__` multi-línea legible (una línea por problema, prefijo `config.<path>: mensaje`).
3. **Parseo:** `load_config(path: Path | str) -> Config`:
   - Lectura con manejo de `OSError` (archivo inexistente/ilegible → `ConfigError` con causa).
   - `json.loads` con captura de `JSONDecodeError` → problema con línea/columna.
   - Validación estructural recursiva sobre dicts crudos **antes** de construir dataclasses (así se reportan problemas de campos ajenos a la construcción).
   - Rechazo de campos desconocidos con sugerencia por distancia de edición (stdlib, sin librerías externas: `difflib.get_close_matches`).
   - Validaciones cruzadas post-construcción (referencias de jobs, unicidad de nombres, coherencia auth).
   - Si hay ≥ 1 problema → `raise ConfigError(problems)`; nunca falla en cascada con el primer error.
   - Resolución de rutas relativas contra `path.parent` (work_dir, log_dir, private_key, gbak_path).
4. **API de soporte:** `Config.validate_semantics()` separado del parseo (para reuso de `odin validate`), y `iter_secret_fields()` que yield-ea `(field_path, value)` de campos sensibles (passwords, passphrase, clave privada) — insumo para el enmascarado del Item 004 y los correos de la Etapa 5.
5. **Tests (`tests/test_config.py` + `tests/fixtures/`):**
   - Fixture válida completa equivalente a los ejemplos de la visión (Linux y Windows, charset ISO8859_1).
   - Parametrizados por regla de validación (un caso inválido por regla mínima).
   - Agregación: JSON con ≥ 3 errores distintos → `ConfigError.problems` los contiene a todos.
   - Defaults: JSON mínimo → valores por defecto correctos.
   - Campos desconocidos: `pasword` → error con sugerencia `password`.
   - Rutas relativas resueltas contra el directorio del JSON.
   - `iter_secret_fields()` lista exactamente los campos sensibles.

## Estrategia de Testing

- Unit tests puros (sin servicios externos, sin filesystem real salvo `tmp_path` de pytest).
- Cobertura de cada regla de validación listada en criterios de aceptación.
- Gates: `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`.

## Dependencias

- **De items anteriores:** Item 001 (estructura del paquete y herramientas) — completado ✅.
- **Bloquea a:** Items 003–007 de la cola (paths, logging, CLI, validate, ejemplos) y toda la Etapa 2+.

## Prerrequisitos de Testing

### Servicios Requeridos
- Ninguno. El parseo/validación de configuración no requiere Firebird, SFTP ni SMTP.

### Configuración de Entorno
- Entorno del Item 001 ya operativo (`uv sync`).
- No requiere variables de entorno, secretos ni puertos.

### Checklist de Validación Manual
- [ ] **Tests pasan:** `uv run pytest -q` verde (nuevos tests de config + smoke previo).
- [ ] **Lint/tipos:** `uv run ruff check . && uv run ruff format --check . && uv run mypy` sin errores.
- [ ] **Funcionalidad verificada:**
  - `uv run python -c "from odin.config import load_config; print(load_config('<fixture válida>'))"` → objeto `Config` con defaults.
  - Fixture con errores → excepción con todos los problemas listados, uno por línea, con `field_path`.
  - JSON con `"pasword"` → error sugiere `password`.
- [ ] **Datos verificados:** fixture mínima aplica los defaults documentados (log_level INFO, gbak_timeout_sec 7200, min_free_mb 1024, sftp_retries 3, host_key_policy strict, log_tail_lines 50).

### Resultados Esperados
- Archivos nuevos: `src/odin/config.py`, `tests/test_config.py`, `tests/fixtures/config_valid_linux.json`, `tests/fixtures/config_valid_windows.json`, `tests/fixtures/` con JSONs inválidos por categoría.
- ≥ 20 tests nuevos pasando; `ConfigError` con reporte agregado demostrado por test.
- Ninguna dependencia nueva en `pyproject.toml` (solo stdlib).

### Plantilla de Documentación de Validación

```markdown
## Validation Results
- [ ] pytest verde (tests de config + smoke)
- [ ] ruff check / format / mypy sin errores
- [ ] Fixture válida parsea con defaults correctos (Linux y Windows)
- [ ] Errores agregados: N problemas reportados simultáneamente
- [ ] Campo desconocido rechazado con sugerencia
- [ ] iter_secret_fields cubre todos los campos sensibles
- [ ] Servicios externos: N/A
```

## Adaptaciones de Plantilla (documentadas)

- Se omite la sección de servicios externos/health checks: el item es lógica pura de parseo. Se reemplaza por validación funcional vía fixtures.
- Se agrega la sección "Requisitos embebidos de detección de errores" para trazar el pedido del solicitante (disco lleno / proceso Firebird / corrupción / verbosidad para DevOps) hacia los campos del esquema y su implementación futura en la Etapa 2.

## Notas para la Etapa 2 (fuera del alcance de este item)

La detección en runtime se especificará en el item correspondiente al respaldo gbak; este esquema ya le provee: timeouts gbak (global y por base), umbral de disco libre, nivel de log y cola de log para el correo. La detección de **corrupción del `.fdb`** se basará en capturar/parsear la salida de gbak (mensajes tipo `database file appears corrupt`, errores de checksum/ODS) y en el exit code del proceso, con volcado completo al log en nivel DEBUG.

## Decisions & Trade-offs

> To be updated during implementation.

(Candidatos a registrar: charset `null` = no pasar flag a gbak; rechazo de campos desconocidos como error en vez de warning; dataclasses frozen vs. mutables; uso de `difflib` para sugerencias; validación de `schedule` solo de forma — 5 campos — dejando la semántica cron a la Etapa 6.)

## Recordatorio de Completado

> **IMPORTANTE:** al completar este item, actualizar `docs/aide/progress.md`: la fila del entregable "Modelo de configuración (dataclasses)..." de la Etapa 1 debe pasar de 📋 → 🚧 → ✅. Este paso es parte de `/speckit.aide.execute-item`.

## Próximo Paso

Iniciar una **nueva sesión de chat** y ejecutar `/speckit.aide.execute-item` con el número **002** para implementar este item.
