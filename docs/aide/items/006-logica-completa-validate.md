# Item 006: Lógica completa de `odin validate`

> **Work item — Paso 5 del flujo AIDE.** Origen: `docs/aide/queue/queue-001.md`, Item 006. Etapa 1 del roadmap.
>
> **Trazabilidad:** visión F3 (última viñeta: "Subcomando de validación del JSON (estructura, conectividad básica, rutas) con mensajes de error claros antes de ejecutar"), F6 (exit codes), C5 ("`odin validate` detecta y describe claramente errores de estructura/rutas del JSON antes de ejecutar") y NFR Seguridad (permisos del JSON, política de host keys — la matriz de `progress.md` asigna ambos a la **Etapa 1**).

---

## Descripción

Cerrar la validación de configuración de la Etapa 1: pasar del `validate` mínimo del Item 005 (parseo + una línea de resumen) a una **validación completa con reporte humano legible que diferencia errores y advertencias**.

Estado actual (Items 001–005 ✅, 117 tests verdes):

- `odin.config.load_config` ya hace validación **estructural** (tipos, rangos, enums, requeridos, campos desconocidos con sugerencia, emails, timezone, forma del `schedule`) y **semántica** (`Config.validate_semantics`: unicidad de nombres, jobs → bases existentes, coherencia `auth.method` ↔ credenciales), con reporte agregado vía `ConfigError.problems` (`field_path: mensaje`).
- `odin.cli._cmd_validate` imprime `Configuración válida: <ruta>` + `bases: N | servidores SFTP: M`, invoca `setup_logging` y devuelve 0/2/1.

Lo que falta y es el núcleo de este item:

1. **Verificación del entorno local** (filesystem) sobre la config ya parseada: `private_key` con método `key`, `work_dir`/`log_dir` existentes o creables, `gbak_path` explícito, permisos del JSON y de la clave, espacio libre vs. `min_free_mb`, y verificaciones de sabor de ruta no checables en el SO actual.
2. **Modelo de reporte con severidades** (ERROR / WARNING / INFO / OK) y renderizado agrupado en consola.
3. **Coherencia de nivel configuración** (no estructural): scheduler habilitado sin jobs, bases no cubiertas por ningún job, `host_key_policy: insecure`, `starttls: false`, ausencia de destinos SFTP, retención desactivada.
4. **`--strict`** para que las advertencias también fallen (exit 2), útil como gate de despliegue/CI.

### Arquitectura

Módulo nuevo **`src/odin/validate.py`** con la lógica de verificación y el renderizado; `src/odin/cli.py` queda como orquestador delgado (parseo de args → `load_config` → `validate_config` → imprimir → exit code). Se separa de la CLI por tres motivos: (a) testeabilidad unitaria de cada check, (b) reuso en el preflight de `odin run` (Etapa 2) y en la **recarga en caliente con validación previa** del modo servicio (Etapa 6: "config inválida no rompe el servicio"), (c) `cli.py` no crece en complejidad ciclomática.

### Principios que rigen todas las verificaciones

- **Solo lectura:** `validate` no crea, modifica ni borra nada (no `mkdir`, no tocar archivos). *Orden obligatorio:* las verificaciones de filesystem corren **antes** que `setup_logging`, porque `setup_logging` (Item 004) hace `resolved_log_dir.mkdir(parents=True, exist_ok=True)` y crearía `work_dir/logs`, enmascarando el hallazgo "work_dir inexistente". Verificado empíricamente en el estado actual.
- **Sin red:** nada de conectividad SFTP/SMTP/Firebird. La "conectividad básica" de la visión F3 queda **fuera de alcance** y se diferirá (ver Fuera de Alcance).
- **Sin secretos en los hallazgos:** los mensajes incluyen `field_path` y rutas, nunca valores de `password`/`passphrase` ni contenido de claves.
- **OS-agnóstico:** una ruta cuyo *sabor* (Windows vs. POSIX, según `odin.paths.is_windows_flavor`) no coincide con el SO anfitrión no se puede verificar: se omite con una nota INFO, nunca se reporta como error. Ídem UNC (evita I/O de red en `validate`).
- **Sin colores ANSI:** salida plana, portable a Windows Server y a redirección a archivo.

## Alcance

| Incluido | Excluido (diferido) |
|---|---|
| Checks de filesystem locales (`work_dir`, `log_dir`, `private_key`, `gbak_path`) | Conectividad SFTP/SMTP/Firebird (Etapas 4–5; posible flag `--check-connections`) |
| Coherencia de scheduler/servidores/notificación sobre el modelo | Auto-detección real de `gbak` en el PATH (lógica de la Etapa 2; acá solo se informa que `null` = auto-detección) |
| Reporte agrupado por severidad + `--strict` | Salida `--json` / máquina-legible (Etapas 6–8, `odin service status`) |
| Advertencias de seguridad de la Etapa 1 (permisos del JSON, `insecure`, `starttls: false`) | Nuevas reglas estructurales/semánticas en `config.py` (no se modifica su API ni sus reglas) |
| Sección de validación en el README | Quickstart multiplataforma completo (Item 009) |

## Criterios de Aceptación

1. **Módulo nuevo `src/odin/validate.py`** (solo stdlib: `os`, `sys`, `stat`, `shutil`, `pathlib`, `enum`, `dataclasses`) con API pública: `Severity`, `Finding`, `ValidationReport`, `validate_config(config, *, host_is_windows=None) -> ValidationReport`, `report_from_config_error(exc, config_path) -> ValidationReport` y `render_report(report, *, strict=False) -> str` (o equivalentes `render_stdout`/`render_stderr`), exportadas en `__all__`.
2. **`Severity`** con cuatro miembros y orden total (`ERROR > WARNING > INFO > OK`) para poder filtrar/agrupar; **`Finding`** frozen con `severity`, `field_path`, `message` y `check` (identificador estable de la verificación, p. ej. `private_key_exists`, útil para tests y para el futuro `--json`).
3. **`ValidationReport`** acumula hallazgos y expone `errors`, `warnings`, `infos`, `oks`, conteos y `is_valid(strict: bool = False) -> bool` (`strict=True` trata advertencias como bloqueantes).
4. **Errores de parseo unificados al formato del reporte:** ante `ConfigError`, cada `ConfigProblem` se convierte en un `Finding(severity=ERROR)` y la salida indica explícitamente que **las verificaciones de entorno no se ejecutaron** porque la configuración no pudo cargarse. Exit code **2** (comportamiento del Item 005 preservado).
5. **Checks de rutas** implementados según la tabla de severidades de abajo, cada uno con su `field_path` exacto (`config.local.work_dir`, `config.servers[i].auth.private_key`, `config.databases[i].gbak_path`, …).
6. **Checks de coherencia/advisorios** implementados según la misma tabla (scheduler habilitado sin jobs, bases no cubiertas por jobs, `host_key_policy: insecure`, `starttls: false`, `servers` vacío, `retention_days: 0`, `compression.password`, permisos del JSON y de la clave privada, espacio libre vs. `min_free_mb`).
7. **Salida humana legible diferenciando errores y advertencias:** el reporte impreso agrupa por severidad con encabezados estables `ERRORES`, `ADVERTENCIAS`, `VERIFICACIONES` y una línea final `Resultado:` con los conteos. Los **errores y el veredicto de invalidez van a stderr**; advertencias, verificaciones OK/INFO, el resumen y el veredicto de validez van a **stdout**. Se conserva la subcadena de resumen del Item 005 (`bases: N | servidores SFTP: M`) para no romper sus tests.
8. **Exit codes:** **0** si no hay errores (aunque haya advertencias) · **2** si hay ≥ 1 error, o si hay advertencias y se pasó `--strict` · **1** ante excepción inesperada (red de `main`, sin cambios) · **2** ante `ConfigError` (sin cambios). `--strict` **no** cambia las severidades reportadas, solo el umbral del exit code, y el veredicto lo menciona.
9. **Flag nuevo `odin validate --strict`** (`action="store_true"`, help que explica que las advertencias pasan a fallar con exit 2). `build_parser` sigue documentando el punto de extensión `run`/`service`.
10. **Orden con `setup_logging`:** las verificaciones de filesystem se ejecutan **antes** de `setup_logging(config)`; la postura del Item 005 (fallo operativo de logging → advertencia + exit 0) se preserva intacta. Demostrado por test: con `work_dir` inexistente pero creable, el reporte dice que no existe **aunque** `setup_logging` lo cree después.
11. **Registro en el log:** línea de resumen única por corrida (nivel INFO sin hallazgos bloqueantes, WARNING si hay advertencias, ERROR si hay errores) con ruta de config y conteos; además cada hallazgo ERROR y WARNING se registra individualmente en su nivel. El reporte detallado **no** se duplica en el logger (evita ruido en consola, que ya lo recibe por stdout/stderr).
12. **Enmascarado coherente:** ningún hallazgo contiene valores de `password`/`passphrase`. Nota de implementación: `Config.iter_secret_fields()` lista la **ruta** de `private_key` como secreto, por lo que en el *archivo de log* esa ruta puede aparecer como `***` (el `MaskingFilter` del Item 004 la reemplaza), mientras que en el reporte impreso por stdout/stderr aparece la ruta real (no es una credencial). Los tests **no** deben afirmar la presencia de la ruta de la clave en el log.
13. **Sin dependencias nuevas** en `pyproject.toml`; sin modificaciones a `config.py`, `paths.py` ni `log.py` (se consume su API pública). `uv run pytest -q` verde; `uv run ruff check .`, `uv run ruff format --check .` y `uv run mypy` (strict) limpios.
14. **Regresión:** los 117 tests de los Items 001–005 siguen pasando **sin cambios de aserciones**. Único ajuste permitido: extender el helper `_write_config` de `tests/test_cli.py` si algún caso nuevo lo requiere (no debería ser necesario: `~/.ssh/id_ed25519` existe en el entorno de desarrollo y un `private_key` ausente es WARNING, no ERROR).
15. **Tests nuevos:** `tests/test_validate.py` (unitarios por check + renderizado + `is_valid`/`--strict` + `report_from_config_error`) y extensión de `tests/test_cli.py` (e2e de `validate` invocando `main([...])` con `capsys`: config limpia → 0; config con advertencias → 0 y `ADVERTENCIAS` en stdout; error de entorno → 2 y `ERRORES` en stderr; `--strict` con advertencias → 2; sabor Windows en Linux → nota de omisión y exit 0; secretos ausentes de stdout/stderr/log). ≥ 20 tests nuevos.
16. **README:** sección "Validación de configuración" con comando, exit codes (0/1/2 y la reserva de 3/4 para la Etapa 5), `--strict` y una nota de que `validate` no toca la red ni crea archivos.

## Tabla de severidades por verificación

> `field_path` entre paréntesis. "Sabor distinto" = la ruta es Windows-flavor en un host POSIX o viceversa (incluye UNC): la verificación se **omite** con nota INFO, nunca falla.

| Check | OK / INFO | WARNING | ERROR |
|---|---|---|---|
| `local.work_dir` | existe y es directorio → **OK**; no existe pero el ancestro existente más cercano es escribible → **INFO** "se creará en la primera ejecución" | no existe y no es creable (ancestro no escribible); sabor distinto (nota de omisión) | existe pero **no es un directorio** (archivo regular) |
| `local.resolved_log_dir` | existe/creable → **OK**/**INFO** | no creable | existe pero es un archivo |
| Espacio libre (`min_free_mb`) | libre ≥ umbral → **OK** (informa MB disponibles) | libre < umbral (`shutil.disk_usage` sobre `work_dir` o su ancestro existente) | — (diferible a la Etapa 2 con entrada en Decisions) |
| `servers[i].auth.private_key` (solo `method: key`) | existe, es archivo y es legible → **OK** | no existe; existe pero no es legible (`os.access(R_OK)`); modo POSIX con bits de grupo/otros (`mode & 0o077`) → "permisos 644, se recomienda 600"; sabor distinto (omisión) | existe pero es un **directorio** |
| `databases[i].gbak_path` | `null` → **INFO** "se auto-detectará (Etapa 2)"; existe, archivo y ejecutable → **OK** | no existe; existe sin `X_OK`; sabor distinto (omisión) | existe pero es un directorio |
| `config` (el propio JSON) | modo POSIX `600`/`400` → **OK** | modo POSIX con bits de grupo/otros (NFR Seguridad: 600/ACL). En Windows se omite con nota INFO (ACL no verificables portables) | — |
| `scheduler` | `enabled: false` → **INFO** "solo modo one-shot"; `enabled: true` con jobs → **OK** (informa timezone y cantidad de jobs) | `enabled: true` con `jobs` vacío ("no se ejecutará ningún respaldo programado"); base no referenciada por ningún job cuando el scheduler está habilitado | — (jobs → bases inexistentes ya es error estructural/semántico en `config.py`) |
| `servers` | lista no vacía → **OK** (nombres + host:port) | `servers` vacío → **INFO** "sin destinos SFTP: las copias quedarán solo en `work_dir`"; `host_key_policy: insecure` → **WARNING** (NFR Seguridad) | — |
| `notification.smtp` | `starttls: true` → **OK** | `starttls: false` → **WARNING** "credenciales SMTP sin cifrar" | — |
| `compression` | `password: null` → **OK** (informa `level`) | — | — |
| `compression.password` | distinto de `null` → **INFO** "cifrado AES-256 (Etapa 3)" | — | — |
| `local.retention_days` | > 0 → **OK** | — | — |
| `local.retention_days` | `0` → **INFO** "sin limpieza automática de respaldos locales" | — | — |

## Formato de salida de referencia

```text
ODIN validate — /ruta/al/config.json
Resumen: bases: 1 | servidores SFTP: 2 | jobs: 1 | scheduler: habilitado (America/Argentina/Buenos_Aires)

ADVERTENCIAS (2):
  [WARN] config: el archivo de configuración tiene permisos 644; se recomienda 600 (credenciales en texto legible)
  [WARN] config.local.work_dir: el directorio no existe y no se puede crear: /var/backups/odin

VERIFICACIONES (9):
  [OK]   config.servers[1].auth.private_key: existe y es legible (/home/usuario/.ssh/id_ed25519)
  [INFO] config.databases[0].gbak_path: es null; se auto-detectará según SO y versión (Etapa 2)
  [INFO] config.scheduler: habilitado con 1 job en America/Argentina/Buenos_Aires
  ...

Resultado: CONFIGURACIÓN VÁLIDA — 0 error(es), 2 advertencia(s)
```

Con errores, el bloque `ERRORES (n):` y la línea `Resultado: CONFIGURACIÓN INVÁLIDA — …` van a **stderr** (el resto a stdout), y si el fallo es de parseo se agrega la línea `No se ejecutaron las verificaciones de entorno: la configuración no pudo cargarse.`

## Pasos de Implementación

1. **`src/odin/validate.py`:** `Severity` (Enum con orden), `Finding`, `ValidationReport` (`add`, propiedades por severidad, `is_valid(strict)`), `report_from_config_error`, `render_report`.
2. **Checks:** una función privada por familia (`_check_config_file`, `_check_work_dir`, `_check_log_dir`, `_check_disk_space`, `_check_private_keys`, `_check_gbak_paths`, `_check_scheduler`, `_check_servers`, `_check_notification`, `_check_compression_retention`) recibiendo `(config, report, host_is_windows)`. Helpers compartidos: `_nearest_existing_ancestor(path)`, `_is_creatable(path)`, `_flavor_mismatch(path, host_is_windows)` (usa `odin.paths.is_windows_flavor`), `_posix_mode_warnings(path)`. `validate_config` las invoca en orden determinista y devuelve el reporte.
3. **`host_is_windows: bool | None = None`** → default `sys.platform == "win32"`. Inyectable para testear ambas direcciones de sabor desde cualquier SO (sin `skipif`).
4. **`src/odin/cli.py`:** agregar `--strict` al subparser `validate`; reescribir `_cmd_validate` como: resolver fuente → `load_config` (con `ConfigError` → `report_from_config_error` + stderr + `EXIT_CONFIG`) → **`validate_config` (antes de logging)** → `setup_logging` vía `_setup_logging_or_warn` (sin cambios) → registrar resumen/hallazgos → imprimir stdout/stderr según criterio 7 → `EXIT_OK`/`EXIT_CONFIG` según `report.is_valid(strict=args.strict)`. Preservar la captura global de `main` y las constantes de exit code.
5. **Tests `tests/test_validate.py`:** un caso por fila de la tabla (usando `tmp_path` para crear archivos/directorios/claves reales, y rutas bajo un archivo regular para forzar ERROR de "no es directorio"), más `host_is_windows=True/False` para las omisiones por sabor, `min_free_mb` descomunal para forzar el WARNING de espacio (determinista), renderizado (encabezados y conteos), `is_valid(strict=…)` y `report_from_config_error`. Fixture `autouse` de limpieza del logger `odin` si se toca logging (mismo patrón que `test_log.py`/`test_cli.py`, reimplementado localmente).
6. **Tests e2e en `tests/test_cli.py`:** según criterio 15, reutilizando `_write_config` (copia del fixture Linux válido con `work_dir` en `tmp_path`) y `mutate=` para cada escenario.
7. **README:** sección "Validación de configuración".
8. **Gates:** `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, más el checklist manual de abajo. Commitear los fuentes apenas pasan los gates (lección del incidente del Item 002).

## Estrategia de Testing

- **Unitarios puros sobre filesystem real de `tmp_path`** (patrón ya usado en `test_log.py`): se crean archivos/directorios/claves con modos específicos; nada de mocks de `os`/`pathlib` (frágiles y poco legibles).
- **Inyección de `host_is_windows`** para cubrir las dos direcciones del contrato OS-agnóstico sin `skipif` y sin depender del SO de corrida. Los checks de modo POSIX (`& 0o077`) sí llevan `skipif(sys.platform == "win32")`.
- **E2E in-process** con `main([...])` + `capsys` (sin subprocess), afirmando exit code, flujo (stdout vs. stderr) y subcadenas estables (`ERRORES`, `ADVERTENCIAS`, `Resultado`, `field_path`). El console script real se verifica a mano.
- **Determinismo:** el WARNING de espacio libre se fuerza con `min_free_mb` enorme (no con lecturas de disco ajustadas); los casos "creable/no creable" se construyen con ancestros escribibles en `tmp_path` y con un archivo regular como padre (falla `mkdir` en ambos SO).
- **Hermeticidad:** fixtures `autouse` de limpieza del logger `odin` y `delenv` de `ODIN_CONFIG` (patrón de `test_cli.py`).
- **Regresión:** los 117 tests previos deben pasar sin edits de aserciones.
- **Gates:** `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`.

## Dependencias

- **De items anteriores:** Item 002 (`Config`, `ConfigError`, `ConfigProblem`, `load_config`, `validate_semantics`, `iter_secret_fields`), Item 003 (`normalize_path`, `is_windows_flavor`), Item 004 (`setup_logging`, `SecretMasker`/`MaskingFilter`, `LOGGER_NAME`), Item 005 (`build_parser`, `main`, `EXIT_*`, `_resolve_config_source`, `_setup_logging_or_warn`) — todos ✅.
- **Bloquea a:** Item 007 (los ejemplos deben pasar `odin validate` con exit 0 → las advertencias no pueden ser bloqueantes por default), Items 008–009 (smoke multiplataforma con `validate`), Etapa 2 (preflight de `odin run` reusa `validate_config`), Etapa 6 (recarga en caliente con validación previa), Etapa 8 (guía de seguridad: permisos del JSON).

## Prerrequisitos de Testing

> **Adaptación de plantilla:** sección adaptada al proyecto — no hay servicios externos (validación estática local, sin red por diseño). El foco del checklist son exit codes, flujos stdout/stderr y efectos de filesystem nulos.

### Servicios Requeridos
- Ninguno. **No** se requieren Firebird, SFTP ni SMTP: `validate` es estático y de solo lectura.

### Configuración de Entorno
- Entorno del Item 001 operativo: `uv sync` (Python 3.14 vía `.python-version`).
- Sin variables de entorno obligatorias (`ODIN_CONFIG` opcional; los tests la aíslan con `monkeypatch.delenv`).
- Sin secretos ni puertos. Archivos de prueba: los fixtures existentes `tests/fixtures/config_valid_{linux,windows}.json`.
- Hechos del entorno de desarrollo (Linux, usuario sin root) que explican los resultados esperados:
  - `~/.ssh/id_ed25519` **existe** con modo `600` → el check de `private_key` da OK en ambos fixtures.
  - Los fixtures tienen modo **644** → disparan la advertencia de permisos del JSON.
  - `/var/backups/odin` (work_dir del fixture Linux) **no es creable** sin root → advertencia esperada.
  - `work_dir` del fixture Windows (`D:\Backups\odin`) → verificación **omitida** en Linux por sabor distinto.

### Checklist de Validación Manual

> Ejecutada el 2026-09-07 en Linux (usuario sin root), Python 3.14.5.

- [x] **Tests pasan:** `uv run pytest -q` → **180 passed** (117 previos sin cambios de aserciones + 63 nuevos: 52 en `tests/test_validate.py`, 11 en `tests/test_cli.py`).
- [x] **Lint/tipos:** `uv run ruff check . && uv run ruff format --check . && uv run mypy` → "All checks passed!", "24 files already formatted", "Success: no issues found in 6 source files".
- [x] **Console script:** `uv run odin validate --help` → `usage: odin validate [-h] [--config RUTA] [--strict]`; `uv run odin --help` sigue listando `validate`.
- [x] **Caso con advertencias (exit 0):** `uv run odin validate --config tests/fixtures/config_valid_linux.json; echo $?` → **0**, stdout con `ADVERTENCIAS (2):` (permisos 644 del JSON + `work_dir` `/var/backups/odin` no creable), `VERIFICACIONES (9):` y `Configuración válida: … — 0 error(es), 2 advertencia(s)`; stderr solo con la advertencia operativa de logging del Item 005 (`Permission denied: '/var/backups/odin'`).
- [x] **`--strict` (exit 2):** mismo comando con `--strict` → **2** con `Configuración inválida (--strict): … — 0 error(es), 2 advertencia(s) tratadas como errores` en stderr y las mismas severidades en stdout.
- [x] **Sabor Windows en Linux (exit 0):** `uv run odin validate --config tests/fixtures/config_valid_windows.json; echo $?` → **0** con `[INFO] config.local.work_dir: verificación omitida: ruta con sabor Windows, no comprobable en POSIX (Linux) (D:/Backups/odin)`, sin errores y sin verificación de espacio libre.
- [x] **Error de entorno (exit 2):** config temporal con `work_dir` → archivo regular y `gbak_path` → directorio → **2** con `ERRORES (2):` (`[ERROR] config.local.work_dir: no es un directorio: existe como un archivo regular`, `[ERROR] config.databases[0].gbak_path: es un directorio; se esperaba el ejecutable gbak`) en **stderr**, y encabezado + `ADVERTENCIAS (1)` (`private_key` inexistente) + `VERIFICACIONES` en **stdout**.
- [x] **Error de parseo (exit 2, comportamiento Item 005):** JSON `{}` → **2** con `ERRORES (4):` (`config.databases`, `config.servers`, `config.notification`, `config.local`), `No se ejecutaron las verificaciones de entorno: la configuración no pudo cargarse.` y `Configuración inválida: … — 4 error(es), 0 advertencia(s)` en stderr.
- [x] **Sin efectos de filesystem:** con `work_dir` inexistente creable, el reporte dice `no existe; se creará en la primera ejecución`; `find` confirma que `<work>/` y `<work>/logs/` aparecen **después** del comando (creados por `setup_logging`, no por las verificaciones). Cubierto además por `test_validate_config_has_no_filesystem_side_effects` y `test_missing_work_dir_is_reported_before_logging_creates_it`.
- [x] **Log y enmascarado:** `<resolved_log_dir>/odin.log` contiene `Configuración válida con advertencias: … (bases: 1 | servidores SFTP: 2 | jobs: 1 | scheduler: … | errores: 0 | advertencias: 2)` más una línea por advertencia; conteo de `masterkey`, `remote-secret-1` y `smtp-secret` en stdout + log → **0**. La ruta de `private_key` figura como `***` en el log (decisión 6) y real en stdout.
- [x] **README:** sección "Validación de configuración" con los tres niveles de comprobación, tabla de exit codes (0/1/2 + reserva 3/4), `--strict` y garantías (solo lectura, sin red, sin secretos, OS-agnóstico).

Comando para el caso de error de entorno (no deja nada en el repo):

```bash
mkdir -p /tmp/odin-v && printf 'x' > /tmp/odin-v/archivo.txt && uv run python - <<'PY'
import json, pathlib
p = pathlib.Path("tests/fixtures/config_valid_linux.json")
d = json.loads(p.read_text(encoding="utf-8"))
d["local"]["work_dir"] = "/tmp/odin-v/archivo.txt"
out = pathlib.Path("/tmp/odin-v/config-workdir-archivo.json")
out.write_text(json.dumps(d), encoding="utf-8")
print(out)
PY
uv run odin validate --config /tmp/odin-v/config-workdir-archivo.json; echo "exit=$?"   # esperado: 2
```

### Resultados Esperados

- **Archivos nuevos:** `src/odin/validate.py`, `tests/test_validate.py`.
- **Archivos modificados:** `src/odin/cli.py` (`--strict` + orquestación del reporte), `tests/test_cli.py` (e2e nuevos), `README.md` (sección de validación), `docs/aide/progress.md` (estado del item).
- **Intactos:** `src/odin/config.py`, `src/odin/paths.py`, `src/odin/log.py`, `tests/fixtures/*.json`, `pyproject.toml` (sin dependencias nuevas).
- **Comportamiento observable:** 11 verificaciones con severidades según la tabla; reporte agrupado con encabezados `ERRORES`/`ADVERTENCIAS`/`VERIFICACIONES`/`Resultado:`; exit codes 0 (válida, con o sin advertencias), 2 (errores o `--strict` con advertencias), 1 (interno); ningún archivo creado/modificado por las verificaciones; ningún secreto en la salida.
- **≥ 20 tests nuevos** pasando; suite total ~137+.

### Plantilla de Documentación de Validación

```markdown
## Validation Results
- [x] Servicio iniciado: N/A (sin servicios externos; validate es estático y sin red)
- [x] Aplicación ejecutada: `uv run odin validate --config <ruta>` verificado en 5 escenarios
      (advertencias → 0, --strict → 2, sabor Windows → 0, error de entorno → 2, parseo → 2)
- [x] Tablas/BD verificadas: N/A
- [x] Datos semilla verificados: fixtures `config_valid_linux.json` (exit 0 + 2 advertencias)
      y `config_valid_windows.json` (exit 0 + 1 advertencia + omisión por sabor)
- [x] Endpoints verificados: N/A (sin red por diseño)
- [x] Screenshots: N/A (CLI); salida textual real pegada en el checklist anterior
- [x] pytest: 180 passed · ruff check/format · mypy: sin errores
- [x] Sin efectos de filesystem: `find` confirma que validate no creó nada por sí mismo
- [x] Enmascarado: 0 apariciones de `masterkey`/`remote-secret-1`/`smtp-secret` en stdout, stderr y `odin.log`
```

## Adaptaciones de Plantilla (documentadas)

- Se omiten "Servicios Requeridos"/"Health checks": el item es validación estática sin red. Se sustituyen por un checklist de **exit codes + flujos stdout/stderr + ausencia de efectos de filesystem**, que es lo verificable.
- Se agrega la **tabla de severidades por verificación** (sección propia): es el contrato central del item y evita ambigüedad sobre qué es error y qué es advertencia.
- Se agregan **Alcance** (incluido/excluido) y **Principios** (solo lectura, sin red, sin secretos, OS-agnóstico, sin colores): fijan límites que el enunciado de la cola no explicita y que condicionan el diseño.
- Se agrega el bloque **Formato de salida de referencia** para que los tests e2e afirmen sobre texto estable.
- Se incluyen "Hechos del entorno de desarrollo" en la configuración de entorno: los resultados esperados del checklist dependen de `~/.ssh/id_ed25519` existente, fixtures en 644 y `/var/backups/odin` no creable.

## Fuera de Alcance (explícito)

- **Conectividad básica** (visión F3): apertura de socket al puerto SFTP/SMTP o ping a Firebird. Motivo: introduce I/O de red, timeouts y falsos negativos en `validate` (un destino temporalmente caído no invalida la configuración); corresponde a `odin run` (Etapas 2–5) y, si se desea, a un flag futuro `--check-connections`. **Dejar entrada en Decisions.**
- **Auto-detección de `gbak`** en el PATH/instalaciones típicas (Etapa 2): `validate` solo informa que `gbak_path: null` implica auto-detección; si el ejecutor de la Etapa 2 expone una función `find_gbak()`, podrá sumarse un check entonces.
- **Validación de `servers[].remote_path` y `databases[].connection`**: semántica remota/dependiente del SO de la base (Item 003 los excluyó de la normalización); su verificación real llega con las Etapas 2 y 4.
- **Salida JSON / `--quiet` / colores**: Etapas 6–8.
- **Nuevas reglas en `config.py`**: si durante la implementación aparece una regla que pertenece al parseo (p. ej. un rango nuevo), **no** se agrega acá: se documenta en Decisions como deuda para un item posterior, para no mezclar contratos.

## Decisions & Trade-offs

> Actualizado durante la implementación (2026-09-07). Las 9 decisiones pre-marcadas quedaron
> resueltas (1–9) y se agregan las de implementación (10–16).

1. **Severidad de `private_key` inexistente: WARNING — confirmado.** Motivo: los ejemplos de la visión (`~/.ssh/id_ed25519`) deben pasar `odin validate` con exit 0 en una máquina limpia (criterio de la Etapa 1 en `progress.md` y requisito del Item 007), y la clave puede aprovisionarse después de validar. El criterio del roadmap ("ruta inexistente de clave privada produce mensajes específicos por campo") se cumple: el hallazgo lleva `field_path` y mensaje explícito, y `--strict` lo vuelve bloqueante. Tests: `test_private_key_missing_is_warning_not_error`, `test_private_key_missing_fails_only_under_strict`. El fallo duro real sigue en la Etapa 4 (autenticación SFTP).
2. **Qué es ERROR en la fase de entorno — confirmado y acotado.** Solo conflictos de *tipo* de archivo, que ningún aprovisionamiento resuelve sin cambiar la configuración: ruta que existe como archivo regular donde se espera un directorio (`work_dir`, `log_dir`) y ruta que existe como directorio donde se espera un archivo (`private_key`, `gbak_path`). Todo lo demás (ausencias, permisos, umbral de disco, coherencia operativa) es WARNING porque es corregible en el entorno. Consecuencia: con parseo exitoso, `validate` solo devuelve 2 por conflictos reales o por `--strict`.
3. **Orden `validate_config` → `setup_logging` — confirmado y testeado.** Las verificaciones son de solo lectura y corren antes del `mkdir` de `log.py`; así el hallazgo "no existe; se creará en la primera ejecución" es verdadero al momento de emitirse. La postura del Item 005 (fallo operativo de logging → advertencia en stderr + exit 0) sigue intacta vía `_setup_logging_or_warn`. Trade-off aceptado: con el fixture Linux real se ven **dos** mensajes por la misma causa raíz (la advertencia de `work_dir` no creable del reporte + la de logging no configurable); se prefirió no suprimir ninguna porque informan cosas distintas (config vs. operación de esta corrida).
4. **Split stdout/stderr — confirmado.** stdout: encabezado + resumen, `ADVERTENCIAS`, `VERIFICACIONES` y el veredicto `Configuración válida: …`. stderr: `ERRORES`, la nota de verificaciones omitidas (solo si el parseo falló) y el veredicto `Configuración inválida: …`. Así el diagnóstico viaja por stderr y el contexto por stdout, y los 15 tests del Item 005 pasan sin tocar una sola aserción.
5. **Duplicación consola/log — aceptada y acotada.** El logger emite una línea de resumen (nivel INFO/WARNING/ERROR según el resultado) **más** cada hallazgo ERROR y WARNING en su nivel: es lo único que queda registrado en modo servicio (Etapa 7, sin consola). Los hallazgos OK/INFO **no** se loguean individualmente (serían ~9 líneas de ruido por corrida). El handler de consola del Item 004 duplica esas líneas a stderr con formato de log; el reporte humano va por stdout. Es la misma duplicación que el Item 005 ya tenía con su única línea.
6. **Ruta de `private_key` enmascarada en el log — se acepta la postura conservadora; `SecretMasker` no se modificó.** Como `Config.iter_secret_fields()` lista el *valor* de `private_key` (que es una ruta), el `MaskingFilter` la reemplaza por `***` en consola de log y archivo. Evidencia real: `… private_key: el archivo no existe; … (***)` en `odin.log` contra la ruta completa en el reporte impreso. Se documenta que el reporte por stdout/stderr no pasa por el masker porque las rutas no son credenciales, y que los tests no deben afirmar la presencia de la ruta de la clave en el log. Alternativa descartada: excluir `private_key` de los secretos (debilita el enmascarado ante un futuro valor pegado por error en ese campo).
7. **Espacio libre (`min_free_mb`) — implementado como advertencia estática.** Se mide con `shutil.disk_usage` sobre `work_dir` o su ancestro existente más cercano y se compara contra el umbral. **Deuda registrada:** el preflight *operativo* (medir justo antes de cada respaldo, con el tamaño estimado del `.fbk`) corresponde a la Etapa 2 y no queda cubierto por este check.
8. **Advertencias de seguridad = WARNING — confirmado.** Permisos del JSON (`mode & 0o077` → "permisos 644; se recomienda 600"), clave privada con acceso de grupo/otros, `host_key_policy: insecure` y `smtp.starttls: false`. En Windows los permisos del JSON se omiten con nota INFO ("las ACL no son comprobables de forma portable"), y `os.access(X_OK)` no es confiable (devuelve True para cualquier archivo existente): documentado en el módulo. Con `--strict` todas pasan a ser bloqueantes, que es el uso previsto (gate de despliegue).
9. **Bases no cubiertas por ningún job = WARNING — confirmado**, pero solo cuando `scheduler.enabled` es true: con scheduler deshabilitado todas las bases son candidatas de `odin run` y la advertencia sería ruido. Test: `test_database_not_covered_by_any_job_warns`.
10. **`log_dir` derivado no se verifica por separado.** Si `local.log_dir` es `null` se emite un INFO ("no configurado; se usará `<work_dir>/logs`") en lugar de duplicar la advertencia del `work_dir`: comparten causa raíz y el directorio efectivo es el mismo árbol. Solo se verifica de forma independiente cuando está configurado explícitamente.
11. **Detección de sabor sobre `as_posix()`, no sobre `str(path)`.** En Windows `str()` ya convirtió `/` en `\`, lo que haría que *toda* ruta pareciera Windows-flavor y ninguna se omitiera. Con `as_posix()` el sabor Windows se reduce a la letra de unidad, y se obtienen tres comportamientos buscados: ruta `D:/…` en Linux → omitida; ruta POSIX en Windows → omitida (evita el falso positivo de anclarla a la unidad actual); UNC en Windows → omitida (sin I/O de red). En Linux `//srv/share` es una ruta local más y sí se verifica.
12. **`host_is_windows` inyectable** en `validate_config` (default `sys.platform == "win32"`): permite ejercitar las dos direcciones del contrato OS-agnóstico desde Linux sin `skipif` ni fixtures condicionales. Los tests de permisos POSIX sí llevan `skipif(Windows o root)`, porque en ninguno de esos dos casos los bits de modo son observables.
13. **Tests sobre el filesystem real de `tmp_path`, sin mocks de `os`/`pathlib`:** más legibles y sin acoplarse a la implementación de los checks. Los helpers `_write_config`/`_dummy_key` dejan la línea de base hermética (JSON en 600, clave privada ficticia en 600, `work_dir` en `tmp_path`), de modo que ningún test depende de `~/.ssh/id_ed25519` ni de los permisos reales de los fixtures del repo. Claves adicionales con otro modo usan un nombre distinto para no pisar la de línea de base. En `tests/test_cli.py` se usó el único ajuste permitido por el criterio 14: extender `_write_config` con los parámetros opcionales `mode` y `private_key` (defaults que preservan el comportamiento previo) y agregar el helper `_key`; **ninguna aserción existente se modificó**.
14. **API de renderizado en tres funciones:** `render_report` (texto completo, usado por tests y como base de la futura salida máquina-legible) y `render_stdout`/`render_stderr` (las vistas partidas que consume la CLI). Trade-off: `render_report` no tiene consumidor en `src/`; se mantiene exportada porque documenta el formato canónico y evita que la lógica de bloques se duplique.
15. **Línea de resumen del log preservada con extensión.** Se mantiene el prefijo literal `Configuración válida` (y la variante `Configuración válida con advertencias`) para que la aserción del Item 005 sobre el contenido de `odin.log` siga pasando, y se le agrega `errores: N | advertencias: M` al resumen existente (`bases | servidores SFTP | jobs | scheduler`).
16. **`--strict` se lee como `bool(args.strict)` y no cambia severidades.** Solo mueve el umbral del exit code (`ValidationReport.is_valid(strict=True)`); el reporte muestra las mismas severidades y el veredicto aclara `(--strict) … tratadas como errores`. El `Namespace` es `Any` para mypy: cada handler lee únicamente sus propias opciones, como ya hacía el Item 005 con `args.config`.
17. **Hallazgo (deuda registrada, fuera del alcance de este item):** en un host POSIX, un `work_dir` con sabor Windows (`D:\Backups\odin`) queda como ruta *relativa* tras `normalize_path` (decisión 1 del Item 003), de modo que `setup_logging` crea un directorio literal `D:/Backups/odin/logs` relativo al CWD. `validate` lo reporta correctamente como verificación omitida (INFO), pero no puede impedir el efecto del logging. Se detectó al ejecutar el fixture Windows por la CLI: el test e2e ahora hace `monkeypatch.chdir(tmp_path)` para no ensuciar el repositorio. Corrección sugerida para una etapa posterior (2 o 7): que `setup_logging` omita el handler de archivo cuando `resolved_log_dir` tiene sabor ajeno al SO anfitrión (reutilizando `odin.paths.is_windows_flavor`), o que `normalize_path` marque esas rutas como no operables.

## Recordatorio de Completado

> **IMPORTANTE:** al completar este item, actualizar `docs/aide/progress.md` (**solo** las filas correspondientes al Item 006, según la regla de scoping de `/speckit.aide.execute-item`):
>
> - Entregable de la Etapa 1 "Estructura de paquete `src/odin/` (`cli.py`, `config.py`, `log.py`, `paths.py`), `tests/`, README inicial": 🚧 → ✅, agregando `validate.py` a la lista de módulos y la nota del Item 006.
> - Criterio de aceptación "JSON inválido produce mensajes específicos por campo (tipo, rango, ruta inexistente)": `[ ]` → `[x]` (la parte de *ruta inexistente* se cubre acá; tipo/rango ya estaban desde el Item 002).
> - Línea "**Última actualización:**" → fecha del día + "(Item 006 completo ✅)".
> - **No** marcar: el criterio `uv sync && uv run odin validate --config examples/config.linux.json` (requiere los ejemplos del Item 007), los entregables de ejemplos/`uv sync` multiplataforma (Items 007–009), ni las filas F3/F6 de la tabla de funcionalidades (se cierran con la etapa).

## Próximo Paso

Item 006 completado (2026-09-07): `src/odin/validate.py` (11 familias de verificación, 180 tests en total), `--strict` en la CLI, sección de validación en el README. Iniciar una **nueva sesión de chat** y ejecutar `/speckit.aide.create-item` con el número **007** (configuraciones de ejemplo y fixtures de test), luego `/speckit.aide.execute-item`.

**Nota para el Item 007:** los ejemplos `examples/config.*.json` deben pasar `odin validate` con exit **0**; con la configuración actual de severidades lo hacen (sus advertencias previsibles son permisos del JSON y `work_dir` no creable en una máquina de desarrollo). Si se los commitea en modo 644 la advertencia de permisos aparecerá siempre: es esperable y no bloqueante (salvo `--strict`).
