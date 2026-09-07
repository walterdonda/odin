# Item 007: Configuraciones de ejemplo y fixtures de test

> **Work item — Paso 5 del flujo AIDE.** Origen: `docs/aide/queue/queue-001.md`, Item 007. Etapa 1 del roadmap.
>
> **Trazabilidad:** visión F3 ("Configuración y autenticación en JSON legible… ejemplos por plataforma en la sección 5"), C5 ("`odin validate` detecta y describe claramente errores de estructura/rutas del JSON antes de ejecutar"), NFR Portabilidad (misma base de código, ejemplos por plataforma), NFR Seguridad (permisos del JSON 600/ACL, documento como riesgo), NFR Mantenibilidad ("documentación de uso con ejemplos reales", pytest). Cierra el entregable de la Etapa 1 "Ejemplos `examples/config.linux.json` y `examples/config.windows.json`" y habilita el criterio de aceptación "`uv sync && uv run odin validate --config examples/config.linux.json` → exit code 0".

---

## Descripción

Dotar al proyecto de **configuraciones de ejemplo listas para copiar** y de una **capa de fixtures de test** que exercising el contrato de configuración completo (válido mínimo, errores y rutas por plataforma), y **verificar que los ejemplos pasan `odin validate` con exit code 0**.

Estado actual (Items 001–006 ✅, 180 tests verdes):

- El contrato de configuración está implementado y validado (`odin.config.load_config` hace validación estructural + semántica con reporte agregado vía `ConfigError.problems`; `odin.paths.normalize_path` resuelve `/` y `\`, `~` y rutas relativas contra el directorio del JSON; `odin.validate.validate_config` verifica entorno local y coherencia con severidades ERROR/WARNING/INFO/OK).
- La CLI `odin validate [--config RUTA] [--strict]` devuelve 0 (válida, aunque haya advertencias), 2 (errores o `--strict` con advertencias) y 1 (interno).
- **No existe el directorio `examples/`.** Los únicos JSON del repo son `tests/fixtures/config_valid_linux.json` y `tests/fixtures/config_valid_windows.json` (datos de prueba con secretos ficticios *reales-looking* —`masterkey`, `remote-secret-1`, `smtp-secret`— usados por los tests de enmascarado de Items 004/006; **no se modifican**).

Lo que falta y es el núcleo de este item:

1. **Ejemplos públicos** `examples/config.linux.json` y `examples/config.windows.json`, fieles a los ejemplos de la visión §5 (charset `ISO8859_1` incluido), con secretos como placeholder `***` (documentación copiable, sin credenciales reales en el repo).
2. **Fixtures de test nuevos** en `tests/fixtures/`: un JSON **válido mínimo** (solo campos requeridos, para verificar defaults), JSON con **errores de tipo / rango / campos faltantes**, y un caso de **rutas relativas + `~`** que complementa los casos por plataforma ya existentes (POSIX absoluto en el fixture Linux, Windows con letra de unidad en el fixture Windows).
3. **Tests** que cargan los ejemplos y fixtures, verifican que los ejemplos pasan `odin validate` (exit 0), que el mínimo aplica defaults, que los de error producen los `field_path` específicos esperados y que las rutas se normalizan.
4. **Documentación**: `examples/README.md` (cómo usar los ejemplos, reemplazar `***`, permisos 600, campos opcionales con sus defaults, comando `odin validate`) y un puntero breve en el `README.md` principal.

### Principios que rigen este item

- **Sin cambios en `src/odin/`.** Este item agrega ejemplos, fixtures, un módulo de tests y documentación; **no toca** el código de producción. Regresión: los 180 tests existentes siguen pasando sin cambios de aserciones.
- **Ejemplos = documentación copiable y segura.** Secretos como `***` (placeholder obvio), nunca credenciales reales. Se commitean en modo 644 → la advertencia de permisos de `validate` es esperada y no bloqueante (exit 0 sin `--strict`).
- **Fieles a la visión.** Los ejemplos reproducen la estructura de `docs/aide/vision.md` §5 (Linux y Windows), que es el contrato canónico que el resto del proyecto referencia.
- **Fixtures de error = contrato de reporte.** Cada fixture de error existe para afirmar que `load_config` reporta los `field_path` específicos por campo (requisito del roadmap: "JSON inválido produce mensajes específicos por campo"), no para duplicar los tests de parseo ya cubiertos en `tests/test_config.py`.
- **OS-agnóstico verificable en Linux.** Los ejemplos y fixtures se verifican en el entorno de desarrollo (Linux). La confirmación en Windows se difiere al Item 009 (smoke multiplataforma); acá se verifica que el ejemplo Windows pasa en Linux con exit 0 (verificación de `work_dir` omitida por sabor distinto, nota INFO).

## Alcance

| Incluido | Excluido (diferido) |
|---|---|
| `examples/config.linux.json` y `examples/config.windows.json` (fieles a la visión) | Quickstart multiplataforma completo y verificación en Windows real (Item 009) |
| `examples/README.md` + puntero breve en `README.md` | Verificación de compatibilidad de dependencias con Python 3.14 (Item 008) |
| Fixtures nuevos: válido mínimo, errores de tipo/rango/campos faltantes, rutas relativas+`~` | Modificar los fixtures existentes `config_valid_{linux,windows}.json` o sus tests |
| `tests/test_fixtures.py`: ejemplos pasan `validate` (exit 0), mínimos→defaults, errores→`field_path`, rutas→normalización | Cambios en `src/odin/` (config/paths/log/validate/cli) |
| Verificación en Linux del ejemplo Linux (exit 0) y del ejemplo Windows (exit 0 con omisión por sabor) | Nuevas reglas de validación o nuevos campos de configuración |

## Criterios de Aceptación

1. **`examples/config.linux.json`** existe y es una copia fiel del ejemplo Linux de la visión §5: una base `nombre_clave_sistema` con `charset: "ISO8859_1"` y `connection` POSIX, `compression.level: 7`, dos servidores SFTP (uno `auth.method: "password"`, otro `auth.method: "key"` con `private_key: "~/.ssh/id_ed25519"`), `notification` con SMTP `starttls: true`, `local.work_dir: "/var/backups/odin"` y `local.retention_days: 7`, y `scheduler` habilitado en `America/Argentina/Buenos_Aires` con un job `"0 2 * * *"`. **Todos los secretos son `***`** (placeholder), no credenciales reales.
2. **`examples/config.windows.json`** existe y es idéntico al Linux salvo los dos campos que cambian por plataforma: `databases[0].connection = "localhost/3050:C:\\Datos\\ERP\\erp.fdb"` y `local.work_dir = "D:\\Backups\\odin"` (barras invertidas escapadas `\\` en JSON).
3. **Ambos ejemplos pasan `odin validate` con exit code 0** en Linux (sin `--strict`): `uv run odin validate --config examples/config.linux.json` → 0 y `uv run odin validate --config examples/config.windows.json` → 0. Las advertencias previsibles (permisos 644 del JSON; `work_dir` `/var/backups/odin` no creable sin root en el Linux; verificación de `work_dir` omitida por sabor Windows en el de Windows) **no** son bloqueantes. Con `--strict` devuelven 2 (esperado; los ejemplos no están pensados para `--strict` tal cual se commitean).
4. **`tests/fixtures/config_minimal.json`**: configuración válida con **solo los campos requeridos** (una base con `name`/`connection`/`user`/`password`; un servidor con `auth.method: "password"`; `notification` con `to`/`from`/`smtp` mínimo; `local` con `work_dir`/`retention_days`). Sin `compression` ni `scheduler`. `load_config` la acepta y aplica **todos los defaults** (ver tabla de defaults abajo).
5. **Fixtures de error** en `tests/fixtures/`, uno por categoría, cada uno por lo demás válido para que los problemas reportados sean exactamente los esperados:
   - `config_error_types.json` → errores de **tipo** (entero como cadena, booleano como cadena).
   - `config_error_ranges.json` → errores de **rango/enum** (puerto fuera de rango, nivel > 9, `retention_days` negativo, enum inválido, timezone desconocida, timeout ≤ 0).
   - `config_error_missing.json` → **campos/secciones requeridas ausentes**.
   Cada uno hace que `load_config` lance `ConfigError` cuyos `problems` incluyen los `field_path` exactos de la tabla de abajo.
6. **`tests/fixtures/config_paths_relative.json`**: configuración válida que ejercita rutas **relativas al JSON** (`work_dir: "./work"`, `log_dir: "logs"`, `gbak_path: "./gbak"`) y expansión de **`~`** (`private_key: "~/.ssh/id_ed25519"`). `load_config` las normaliza a rutas absolutas: las relativas contra el directorio del fixture (`tests/fixtures/`), `~` contra el home.
7. **Casos de rutas por plataforma cubiertos:** el fixture Linux existente aporta el caso POSIX absoluto, el fixture Windows existente el caso con letra de unidad, y `config_paths_relative.json` el caso relativo+`~`. El módulo de tests afirma la normalización de los tres.
8. **`tests/test_fixtures.py`** (nuevo) con, como mínimo: (a) los ejemplos cargan y su `charset` es `ISO8859_1`; (b) los ejemplos pasan `main(["validate", "--config", …]) == EXIT_OK` (con `monkeypatch.chdir(tmp_path)` para contener el efecto de logging de ruta relativa del ejemplo Windows — ver Decisión 5); (c) `validate_config(load_config(ejemplo)).is_valid(strict=False)` es `True` (verificación pura, sin efectos); (d) el mínimo aplica defaults; (e) cada fixture de error reporta los `field_path` esperados; (f) las rutas relativas/`~` se normalizan; (g) guard: todo `examples/*.json` y `tests/fixtures/*.json` parsea como objeto JSON. **≥ 10 tests nuevos.**
9. **`examples/README.md`**: propósito de los ejemplos, instrucción de reemplazar `***`, advertencia de seguridad (permisos `600`/ACL, excluir de VCS el JSON real), comando `odin validate` con exit codes, y una tabla/lista de los **campos opcionales** que la visión no muestra con sus defaults (ver tabla abajo). **`README.md`** principal: subsección breve "Ejemplos de configuración" que apunta a `examples/`.
10. **Formato de los JSON:** UTF-8, indentación de 2 espacios, sin comentarios, newline final; barras invertidas de Windows escapadas (`\\`). **Sin secretos reales** en ningún archivo commiteado.
11. **Sin dependencias nuevas** en `pyproject.toml`; **sin cambios en `src/odin/`** ni en los fixtures/tests existentes. Gates verdes: `uv run pytest -q` (180 previos + nuevos), `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy` (sin cambios en `src/`, sigue limpio).

### Tabla de defaults que debe verificar el fixture mínimo

Al omitir secciones/campos opcionales en `config_minimal.json`, `load_config` debe producir (Item 002):

| Campo | Default |
|---|---|
| `compression.level` / `compression.password` | `7` / `None` |
| `scheduler.enabled` / `.timezone` / `.jobs` | `False` / `"UTC"` / `[]` |
| `servers[i].host_key_policy` | `HostKeyPolicy.STRICT` |
| `notification.log_tail_lines` | `50` |
| `notification.smtp.starttls` | `True` |
| `local.log_level` | `LogLevel.INFO` |
| `local.min_free_mb` | `1024` |
| `local.gbak_timeout_sec` | `7200` |
| `local.sftp_retries` / `.sftp_connect_timeout_sec` | `3` / `30` |
| `local.resolved_log_dir` | `work_dir / "logs"` |
| `databases[i].role` / `.charset` / `.gbak_path` / `.gbak_timeout_sec` | `None` |

## Contenido de referencia

### `examples/config.linux.json` (fiel a visión §5)

```json
{
  "databases": [
    {
      "name": "nombre_clave_sistema",
      "connection": "localhost/3050:/var/lib/firebird/data/erp.fdb",
      "user": "SYSDBA",
      "password": "***",
      "role": null,
      "charset": "ISO8859_1",
      "gbak_path": null
    }
  ],
  "compression": {
    "level": 7,
    "password": null
  },
  "servers": [
    {
      "name": "sitio-alterno-1",
      "host": "203.0.113.10",
      "port": 22,
      "username": "odin",
      "auth": { "method": "password", "password": "***" },
      "remote_path": "/backups/firebird/"
    },
    {
      "name": "sitio-alterno-2",
      "host": "backup.example.com",
      "port": 2222,
      "username": "odin",
      "auth": { "method": "key", "private_key": "~/.ssh/id_ed25519", "passphrase": null },
      "remote_path": "/srv/backups/firebird/"
    }
  ],
  "notification": {
    "to": "control@example.com",
    "from": "odin-backups@example.com",
    "smtp": {
      "host": "smtp.example.com",
      "port": 587,
      "starttls": true,
      "username": "odin-backups@example.com",
      "password": "***"
    }
  },
  "local": {
    "work_dir": "/var/backups/odin",
    "retention_days": 7
  },
  "scheduler": {
    "enabled": true,
    "timezone": "America/Argentina/Buenos_Aires",
    "jobs": [
      {
        "databases": ["nombre_clave_sistema"],
        "schedule": "0 2 * * *",
        "on_misfire": "run_once",
        "skip_if_running": true
      }
    ]
  }
}
```

### `examples/config.windows.json`

Idéntico al anterior **salvo** estos dos campos (barras invertidas escapadas en JSON):

```jsonc
"databases": [ { /* … */ "connection": "localhost/3050:C:\\Datos\\ERP\\erp.fdb", /* … */ } ],
"local": { "work_dir": "D:\\Backups\\odin", "retention_days": 7 }
```

### `tests/fixtures/config_minimal.json`

```json
{
  "databases": [
    {
      "name": "bd_minima",
      "connection": "localhost/3050:/var/lib/firebird/data/min.fdb",
      "user": "SYSDBA",
      "password": "masterkey"
    }
  ],
  "servers": [
    {
      "name": "destino-1",
      "host": "203.0.113.20",
      "port": 22,
      "username": "odin",
      "auth": { "method": "password", "password": "remote-secret" },
      "remote_path": "/backups/firebird/"
    }
  ],
  "notification": {
    "to": "control@example.com",
    "from": "odin-backups@example.com",
    "smtp": {
      "host": "smtp.example.com",
      "port": 587,
      "username": "odin-backups@example.com",
      "password": "smtp-secret"
    }
  },
  "local": {
    "work_dir": "/var/backups/odin",
    "retention_days": 7
  }
}
```

### `tests/fixtures/config_paths_relative.json`

```json
{
  "databases": [
    {
      "name": "bd_rutas",
      "connection": "localhost/3050:/var/lib/firebird/data/rutas.fdb",
      "user": "SYSDBA",
      "password": "masterkey",
      "gbak_path": "./gbak"
    }
  ],
  "servers": [
    {
      "name": "destino-key",
      "host": "backup.example.com",
      "port": 22,
      "username": "odin",
      "auth": { "method": "key", "private_key": "~/.ssh/id_ed25519", "passphrase": null },
      "remote_path": "/srv/backups/firebird/"
    }
  ],
  "notification": {
    "to": "control@example.com",
    "from": "odin-backups@example.com",
    "smtp": {
      "host": "smtp.example.com",
      "port": 587,
      "username": "odin-backups@example.com",
      "password": "smtp-secret"
    }
  },
  "local": {
    "work_dir": "./work",
    "retention_days": 7,
    "log_dir": "logs"
  }
}
```

Normalización esperada (`base_dir` = ruta absoluta de `tests/fixtures/`):

| Campo | Valor en JSON | Resultado de `load_config` |
|---|---|---|
| `local.work_dir` | `"./work"` | `<abs tests/fixtures>/work` |
| `local.log_dir` | `"logs"` | `<abs tests/fixtures>/logs` |
| `databases[0].gbak_path` | `"./gbak"` | `"<abs tests/fixtures>/gbak"` (string) |
| `servers[0].auth.private_key` | `"~/.ssh/id_ed25519"` | `"<home>/.ssh/id_ed25519"` (string) |

### Fixtures de error — contrato de `field_path` reportados

> Cada fixture es por lo demás válido: `load_config` lanza `ConfigError` con **exactamente** los problemas de la tabla (agregados en una sola pasada). El test afirma que el conjunto de `field_path` esperados está contenido en `exc.problems`.

**`config_error_types.json`** — base válida con estos 5 valores de tipo incorrecto:

| `field_path` | Valor en JSON | Mensaje (subcadena) |
|---|---|---|
| `config.compression.level` | `"7"` (cadena) | `debe ser un entero` |
| `config.servers[0].port` | `"22"` (cadena) | `debe ser un entero` |
| `config.notification.smtp.starttls` | `"yes"` (cadena) | `debe ser un booleano` |
| `config.local.retention_days` | `"7"` (cadena) | `debe ser un entero` |
| `config.scheduler.enabled` | `"true"` (cadena) | `debe ser un booleano` |

**`config_error_ranges.json`** — base válida con estos 6 valores fuera de rango/enum:

| `field_path` | Valor en JSON | Mensaje (subcadena) |
|---|---|---|
| `config.servers[0].port` | `70000` | `debe ser un entero <= 65535` |
| `config.compression.level` | `12` | `debe ser un entero <= 9` |
| `config.local.retention_days` | `-1` | `debe ser un entero >= 0` |
| `config.servers[0].host_key_policy` | `"lax"` | `valor inválido 'lax'` |
| `config.scheduler.timezone` | `"Marte/Olympus_Mons"` | `zona horaria desconocida` |
| `config.databases[0].gbak_timeout_sec` | `0` | `debe ser un entero > 0` |

**`config_error_missing.json`** — faltan estos 4 campos/secciones requeridos:

| `field_path` | Ausencia | Mensaje (subcadena) |
|---|---|---|
| `config.databases[0].password` | campo omitido | `campo requerido ausente` |
| `config.servers[0].auth` | campo omitido | `campo requerido ausente` |
| `config.notification.to` | campo omitido | `campo requerido ausente` |
| `config.local` | sección omitida | `sección requerida ausente` |

> Nota: al fallar la validación estructural, `load_config` **no** llega a `validate_semantics`; por eso no aparecen problemas semánticos (p. ej. `auth.password` requerido). Los 4 problemas de arriba son los únicos reportados.

## Pasos de Implementación

1. **Crear `examples/`** y los dos JSON de ejemplo (fieles a la visión §5, secretos `***`, 2 espacios, newline final). Verificar que parsean: `uv run python -c "import json,pathlib; [json.loads(p.read_text()) for p in pathlib.Path('examples').glob('*.json')]"`.
2. **Verificar exit 0 manualmente** (Linux): `uv run odin validate --config examples/config.linux.json; echo $?` y lo mismo con el de Windows → ambos `0`.
3. **Crear los fixtures nuevos** en `tests/fixtures/`: `config_minimal.json`, `config_paths_relative.json`, `config_error_types.json`, `config_error_ranges.json`, `config_error_missing.json` (contenido según la sección de referencia). **No** modificar los fixtures existentes.
4. **Crear `tests/test_fixtures.py`** siguiendo el patrón de los módulos existentes: `from __future__ import annotations`, fixtures `autouse` locales `clean_odin_logger` (cierra handlers del logger `odin`) y `clean_env` (`monkeypatch.delenv(ENV_CONFIG_VAR, raising=False)`) — **reimplementadas localmente** (no hay `conftest.py` compartido y no se introduce uno en este item, ver Decisión 6). Constantes `EXAMPLES = Path(__file__).parent.parent / "examples"` y `FIXTURES = Path(__file__).parent / "fixtures"`.
5. **Tests** (criterio 8): parametrizar ejemplos; usar `main([...])` in-process con `monkeypatch.chdir(tmp_path)`; `pytest.raises(ConfigError)` para los de error y afirmar `field_path` esperados ⊆ `{p.field_path for p in exc.value.problems}`; para rutas relativas comparar contra `(FIXTURES / "config_paths_relative.json").parent.absolute()`; guard que recorre `examples/*.json` + `tests/fixtures/*.json` con `json.loads`.
6. **`examples/README.md`** y subsection breve en **`README.md`** (criterio 9).
7. **Gates:** `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`. Commitear los fuentes y fixtures apenas pasan los gates (lección del incidente del Item 002: no dejar trabajo sin commit).

## Estrategia de Testing

- **Ejemplos vía CLI in-process:** `main(["validate", "--config", str(ejemplo)]) == EXIT_OK` con `capsys`. Refleja el comando del criterio de aceptación de la Etapa 1. Se usa **`monkeypatch.chdir(tmp_path)`** porque el ejemplo Windows, en Linux, deja el `work_dir` `D:\Backups\odin` como ruta *relativa* tras `normalize_path` (Decisión 1 del Item 003) y `setup_logging` crearía un directorio literal `D:/Backups/odin/logs` relativo al CWD (deuda conocida, Decisión 17 del Item 006). Con `chdir(tmp_path)` ese efecto queda contenido en el tmp de pytest. Verificado empíricamente en la preparación de este item.
- **Verificación pura complementaria:** `validate_config(load_config(ejemplo)).is_valid(strict=False) is True` — determinista y sin efectos de filesystem/logging. Cubre el "pasan validate" sin depender del CWD ni de handlers.
- **Robustez ante el entorno:** los tests **no** afirman el número exacto de advertencias (depende de si `~/.ssh/id_ed25519` existe y de si `/var/backups/odin` es creable en la máquina); afirman exit 0 / `is_valid(strict=False)` y el `charset == "ISO8859_1"` (estables). La advertencia por `private_key` ausente es WARNING (no bloqueante), y la de permisos 644 también → exit 0 se mantiene en cualquier máquina.
- **Fixtures de error sobre archivo real:** se cargan con `load_config(FIXTURES / "…")` (no se construyen en memoria) para que el fixture *sea* el artefacto verificable y pueda usarse también en demos manuales de `odin validate`.
- **Rutas relativas:** comparación contra la ruta absoluta del directorio de fixtures (`config_path.parent.absolute()`), que es la base que usa `normalize_path`.
- **Guard de JSON válidos:** un test recorre todos los `.json` de `examples/` y `tests/fixtures/` y afirma que parsean como `dict`; evita commitear fixtures rotos.
- **Hermeticidad:** fixtures `autouse` de limpieza del logger `odin` y `delenv` de `ODIN_CONFIG` (patrón de `test_cli.py`/`test_log.py`/`test_validate.py`).
- **Regresión:** los 180 tests previos pasan sin edits (no se tocan fixtures ni tests existentes).
- **Gates:** `uv run pytest -q`, `uv run ruff check .` (aplica a `tests/`), `uv run ruff format --check .`, `uv run mypy` (solo `src/odin`, sin cambios).

## Dependencias

- **De items anteriores:** Item 002 (`load_config`, `Config`, `ConfigError`, `ConfigProblem`, enums y defaults), Item 003 (`normalize_path`, resolución relativa contra el dir del JSON, `is_windows_flavor`), Item 005/006 (`main`, `EXIT_OK`, `validate_config`, `ValidationReport.is_valid`, `--strict`) — todos ✅.
- **Bloquea a:** criterio de aceptación de la Etapa 1 (`odin validate --config examples/config.linux.json` → 0), Item 009 (smoke multiplataforma que corre `validate` sobre `examples/config.<plataforma>.json`), Etapa 8 (README completo y guía de seguridad toman los ejemplos como base).

## Prerrequisitos de Testing

> **Adaptación de plantilla:** sección adaptada al proyecto — no hay servicios externos (configuración estática, sin red por diseño). El foco del checklist son los exit codes de `odin validate` sobre los ejemplos y la ausencia de efectos de filesystem no deseados en el repo.

### Servicios Requeridos
- Ninguno. **No** se requieren Firebird, SFTP ni SMTP: `validate` es estático, de solo lectura y sin red (Item 006). Los ejemplos apuntan a hosts/paths ilustrativos (`example.com`, `203.0.113.x` — RFC 5737) que nunca se contactan.

### Configuración de Entorno
- Entorno del Item 001 operativo: `uv sync` (Python 3.14 vía `.python-version`).
- Sin variables de entorno obligatorias (`ODIN_CONFIG` opcional; los tests la aíslan con `monkeypatch.delenv`).
- Sin secretos ni puertos. Archivos de prueba: los ejemplos y fixtures creados por este item.
- Hechos del entorno de desarrollo (Linux, usuario sin root) que explican los resultados esperados:
  - Los ejemplos se commitean en modo **644** → disparan la advertencia de permisos del JSON (no bloqueante, exit 0).
  - `/var/backups/odin` (`work_dir` del ejemplo Linux) **no es creable** sin root → advertencia esperada (no bloqueante).
  - `~/.ssh/id_ed25519` puede existir (→ OK) o no (→ WARNING no bloqueante); el exit 0 no depende de esto.
  - `work_dir` del ejemplo Windows (`D:\Backups\odin`) → verificación **omitida** en Linux por sabor distinto (INFO). Al correrlo por la CLI desde el repo, `setup_logging` crearía un dir relativo literal `D:/Backups/odin/logs`: **correr la verificación manual del ejemplo Windows desde un directorio temporal** (o limpiarlo después). Los tests usan `monkeypatch.chdir(tmp_path)` y no ensucian el repo.

### Checklist de Validación Manual

> Ejecutada el 2026-09-07 en Linux (usuario sin root), Python 3.14.5.

- [x] **Build/instalación:** `uv sync` sin errores (entorno del Item 001 operativo).
- [x] **Tests pasan:** `uv run pytest -q` → **196 passed** (180 previos sin cambios + 16 nuevos: 10 funciones en `tests/test_fixtures.py`, varias parametrizadas ×2/×3).
- [x] **Lint/tipos:** `uv run ruff check .` → "All checks passed!"; `uv run ruff format --check .` → "26 files already formatted"; `uv run mypy` → "Success: no issues found in 6 source files" (sin cambios en `src/`).
- [x] **JSON válidos:** guard `test_all_json_files_parse_as_objects` recorre 9 archivos (2 ejemplos + 7 fixtures) y todos parsean como `dict`; además `python -c "import json,pathlib; …"` sobre `examples/*.json` → OK.
- [x] **Ejemplo Linux pasa validate (exit 0):** `uv run odin validate --config examples/config.linux.json; echo $?` → **0**, stdout con `ADVERTENCIAS (2):` (permisos 644 del JSON + `work_dir` `/var/backups/odin` no creable) y `Configuración válida: … — 0 error(es), 2 advertencia(s)`; stderr solo con la advertencia operativa de logging del Item 005 (`Permission denied: '/var/backups/odin'`).
- [x] **Ejemplo Windows pasa validate (exit 0) en Linux:** desde un cwd temporal, `.venv/bin/odin validate --config <repo>/examples/config.windows.json; echo $?` → **0**, con `[INFO] config.local.work_dir: verificación omitida: ruta con sabor Windows, no comprobable en POSIX (Linux) (D:/Backups/odin)`, `ADVERTENCIAS (1):` (permisos 644) y sin errores. El `setup_logging` creó `D:/Backups/odin/logs/odin.log` **dentro del cwd temporal** (contenido y limpiado). Verificación en Windows real → Item 009.
- [x] **`--strict` falla (exit 2), como se espera:** `uv run odin validate --config examples/config.linux.json --strict; echo $?` → **2** (las advertencias de permisos/`work_dir` se tratan como errores). Los ejemplos son plantilla, no están pensados para pasar `--strict` sin editar.
- [x] **Sin secretos reales:** `grep -rn '"password"' examples/` muestra solo `***` (y `null` en `compression.password`/`passphrase`); `grep -rn 'masterkey\|remote-secret\|smtp-secret' examples/` → **0** coincidencias. Test `test_examples_secrets_are_placeholders` lo afirma para ambos ejemplos.
- [x] **Sin efectos de filesystem en el repo:** tras `uv run pytest -q`, `git status --short` lista solo los archivos esperados del item y `find . -name 'D:*' -not -path './.venv/*'` → vacío (el efecto de logging del ejemplo Windows quedó en `tmp_path`).
- [x] **Fixtures de error verificables a mano:** `uv run odin validate --config tests/fixtures/config_error_types.json; echo $?` → **2** con 5 hallazgos `[ERROR]` (más el encabezado `ERRORES`) en stderr; por test, los tres fixtures de error reportan exactamente los `field_path` de la tabla.
- [x] **README/`examples/README.md`:** `examples/README.md` con propósito, tabla por plataforma, instrucción de reemplazar `***`, seguridad (permisos 600/ACL, no versionar el JSON real), `odin validate` + exit codes y tabla de campos opcionales con defaults; `README.md` principal con subsección "Ejemplos de configuración" que apunta a `examples/`.


Comando sugerido para la verificación manual del ejemplo Windows sin ensuciar el repo:

```bash
tmp=$(mktemp -d) && (cd "$tmp" && /ruta/al/repo/.venv/bin/odin validate --config /ruta/al/repo/examples/config.windows.json; echo "exit=$?"); rm -rf "$tmp"
```

### Resultados Esperados

- **Archivos nuevos:** `examples/config.linux.json`, `examples/config.windows.json`, `examples/README.md`, `tests/fixtures/config_minimal.json`, `tests/fixtures/config_paths_relative.json`, `tests/fixtures/config_error_types.json`, `tests/fixtures/config_error_ranges.json`, `tests/fixtures/config_error_missing.json`, `tests/test_fixtures.py`.
- **Archivos modificados:** `README.md` (subsección "Ejemplos de configuración"), `docs/aide/progress.md` (estado del item).
- **Intactos:** `src/odin/**` (sin cambios), `tests/fixtures/config_valid_{linux,windows}.json`, `tests/test_{config,paths,log,cli,validate,smoke}.py`, `pyproject.toml`.
- **Comportamiento observable:** `odin validate --config examples/config.linux.json` → exit **0**; ídem el de Windows en Linux → exit **0** (omisión por sabor). Los fixtures de error → `ConfigError` con los `field_path` de la tabla. El fixture mínimo → todos los defaults de la tabla. Rutas relativas/`~` → normalizadas a absolutas.
- **≥ 10 tests nuevos** pasando; suite total ~190+.

### Plantilla de Documentación de Validación

```markdown
## Validation Results
- [x] Servicio iniciado: N/A (sin servicios externos; validate es estático y sin red)
- [x] Aplicación ejecutada: `odin validate` sobre examples/config.linux.json (exit 0, 2 advertencias) y
      examples/config.windows.json en Linux (exit 0, omisión por sabor); --strict sobre linux → exit 2
- [x] Tablas/BD verificadas: N/A
- [x] Datos semilla verificados: ejemplos (charset ISO8859_1, 2 servidores password+key, scheduler
      America/Argentina/Buenos_Aires, secretos `***`) y fixtures (mínimo→todos los defaults,
      3 de error→field_path exactos sin extras, rutas relativas+`~`→normalización)
- [x] Endpoints verificados: N/A (sin red por diseño)
- [x] Screenshots: N/A (CLI); salida textual real pegada en el checklist anterior
- [x] pytest: 196 passed (180 previos + 16 nuevos) · ruff check/format · mypy: sin errores
- [x] Sin secretos reales en examples/ (solo `***`); git status sin efectos `D:` tras los tests
```


## Adaptaciones de Plantilla (documentadas)

- Se omiten "Servicios Requeridos"/"Health checks": el item es configuración estática sin red. Se sustituyen por un checklist de **exit codes de `odin validate` sobre los ejemplos + ausencia de efectos de filesystem en el repo + ausencia de secretos reales**, que es lo verificable.
- Se agrega la sección **Contenido de referencia** con el JSON exacto de ejemplos y fixtures clave, y la **tabla de `field_path`** de los fixtures de error: son el contrato contra el que se escriben las aserciones y evita ambigüedad.
- Se agrega la **tabla de defaults** que debe verificar el fixture mínimo (deriva del modelo del Item 002).
- Se incluyen "Hechos del entorno de desarrollo" porque los resultados esperados del checklist dependen de permisos 644, `/var/backups/odin` no creable y la presencia opcional de `~/.ssh/id_ed25519`.
- Se documenta explícitamente el **efecto de ruta relativa del ejemplo Windows en Linux** (Decisión 17 del Item 006) y cómo conterlo (`chdir(tmp_path)` en tests, cwd temporal en la verificación manual).

## Fuera de Alcance (explícito)

- **Verificación en Windows real** del ejemplo Windows (corre en el Item 009 / manual en máquina Windows). Acá solo se verifica que pasa en Linux con exit 0 (omisión por sabor).
- **Campos opcionales de confiabilidad/observabilidad en los ejemplos** (`min_free_mb`, `sftp_retries`, `host_key_policy`, `log_level`, timeouts, `log_tail_lines`, `compression.password`, cifrado AES): la visión §5 no los muestra y el contrato OS-agnóstico canónico se mantiene fiel a ella. Se **documentan en `examples/README.md`** con sus defaults (Decisión 2), no se agregan a los JSON de ejemplo.
- **Un `conftest.py` compartido** para las fixtures `autouse` de limpieza de logger/entorno: se sigue el patrón establecido de reimplementarlas localmente por módulo (Decisión 6); unificarlas es una refactorización de la arquitectura de tests fuera de este item.
- **Nuevas reglas de validación o nuevos campos de configuración.** Si durante la implementación aparece un caso que pertenece al parseo (p. ej. un rango nuevo), **no** se agrega acá: se documenta en Decisions como deuda para un item posterior.
- **Corrección de la deuda del Item 006 (Decisión 17)** sobre `setup_logging` creando dirs de sabor ajeno: se documenta y se contiene (chdir), pero la corrección de fondo corresponde a una etapa posterior (2 o 7).
- **Guía de seguridad completa** (Etapas 8): `examples/README.md` siembra la recomendación de permisos 600/ACL y exclusión de VCS, pero la guía integral es de la Etapa 8.

## Decisions & Trade-offs

> Actualizado durante la implementación (2026-09-07). Las 7 decisiones pre-marcadas
> quedaron **confirmadas** (se aplicaron sin cambios) y se agregan las de
> implementación (8–10).
>
> Decisiones de diseño de este work item:

1. **Ejemplos fieles a la visión §5, con secretos `***`.** Se prioriza que los ejemplos sean la referencia canónica y copiable del contrato OS-agnóstico (como los usa el resto del proyecto y la Etapa 8), y que sean **seguros para commitear** (placeholders obvios, cero credenciales reales). Trade-off: `***` no demuestra el enmascarado (los fixtures `config_valid_*` existentes, con secretos ficticios reales-looking, sí lo hacen y no se tocan). Los `***` pasan `validate` porque son cadenas no vacías.
2. **Campos opcionales fuera de los JSON de ejemplo, documentados en `examples/README.md`.** Mantiene los ejemplos alineados 1:1 con la visión (el enunciado de la cola dice "a partir de los ejemplos de la visión") y evita sugerir que son requeridos. Trade-off: un usuario que solo mira el JSON no ve `min_free_mb`/`host_key_policy`/etc.; se mitiga con la lista de opcionales + defaults en el README de ejemplos.
3. **Fixtures de error por categoría (tipos / rangos / faltantes), cada uno "por lo demás válido".** Permite afirmar `field_path` exactos y demostrable a mano con `odin validate`, sin el ruido de una config con errores mezclados. Trade-off: cierta superposición con `tests/test_config.py` (que prueba lo mismo construyendo dicts en memoria); se justifica porque el fixture *archivo* es un artefacto reusable (demos, docs) y el item lo pide explícitamente.
4. **`config_paths_relative.json` como caso de rutas nuevo; los por-plataforma absolutos se reusan de los fixtures Linux/Windows existentes.** Aporta cobertura de rutas relativas + `~` (que los existentes no tienen, pues usan absolutos) sin duplicar los casos POSIX/Windows absolutos. Trade-off: el fixture relativo resuelve contra `tests/fixtures/` (acoplado a esa ubicación); es determinista y se documenta.
5. **Contener el efecto de logging del ejemplo Windows con `monkeypatch.chdir(tmp_path)` en tests y cwd temporal en la verificación manual.** Es la mitigación disponible hoy para la deuda del Item 006 (Decisión 17: `setup_logging` crea un dir relativo literal `D:/…` en hosts POSIX). Trade-off: no corrige la deuda de fondo (diferida a Etapa 2/7); se documenta para que no sorprenda.
6. **Sin `conftest.py` compartido; fixtures `autouse` reimplementadas localmente en `test_fixtures.py`.** Respeta el patrón de los módulos de test actuales (cada uno define su limpieza de logger/entorno) y evita una refactorización transversal fuera de alcance. Trade-off: ligera duplicación de ~10 líneas de fixtures de limpieza.
7. **Verificación en Windows diferida al Item 009.** El entorno de desarrollo es Linux; exigir Windows acá bloquearía el item. Se verifica el exit 0 del ejemplo Windows *en Linux* (omisión por sabor) y se deja la validación nativa para el smoke multiplataforma.
8. **Los tests de errores afirman `field_path` ⊆ reportados + subcadena del mensaje** (no solo el subconjunto de rutas). Verificado en la implementación: los tres fixtures producen **exactamente** los `field_path` de la tabla, sin extras (`config_error_types` → 5, `config_error_ranges` → 6, `config_error_missing` → 4). Se afirma el subconjunto (no la igualdad) para que un futuro check agregado en `config.py` no rompa el test, y se agrega la subcadena del mensaje para verificar también el *motivo*, no solo la ubicación.
9. **Tests adicionales de seguridad y de diferencia por plataforma.** Se suman `test_examples_secrets_are_placeholders` (afirma `password == "***"` en base/servidor/SMTP → verifica que ningún ejemplo commitea credenciales reales) y `test_windows_example_differs_only_in_platform_fields` (afirma que `connection` y `work_dir` cambian y el resto del contrato coincide). Refuerzan los criterios 1–2 y el NFR Seguridad sin costo.
10. **`EXAMPLES`/`FIXTURES` absolutos vía `Path(__file__).resolve()`.** Necesario porque el test de CLI hace `monkeypatch.chdir(tmp_path)` y luego invoca `main([...])` con la ruta del ejemplo: si fuera relativa, no resolvería tras el `chdir`. `BASE_DIR` (para el fixture relativo) se deriva del mismo path resuelto, de modo que coincide con el `config_path.parent.absolute()` que computa `load_config`.


## Recordatorio de Completado

> **IMPORTANTE:** al completar este item, actualizar `docs/aide/progress.md` (**solo** las filas correspondientes al Item 007, según la regla de scoping de `/speckit.aide.execute-item`):
>
> - Entregable de la Etapa 1 "📋 Ejemplos `examples/config.linux.json` y `examples/config.windows.json`": 📋 → ✅, con nota del Item 007 (fieles a la visión, charset ISO8859_1, secretos `***`, verificados con `odin validate` exit 0 en Linux; `examples/README.md`).
> - Criterio de aceptación "[ ] `uv sync && uv run odin validate --config examples/config.linux.json` → exit code 0": `[ ]` → `[x]`, aclarando **verificado en Linux** (Windows queda para el Item 009).
> - Criterio de aceptación "[ ] Tests unitarios de parseo, normalización de rutas y enmascarado de secretos": `[ ]` → `[x]` — el parseo (Item 002), la normalización (Item 003) y el enmascarado (Item 004) ya tienen tests unitarios verdes; el Item 007 agrega la capa de fixtures/ejemplos. Marcarlo porque tras este item la afirmación es completamente cierta.
> - Línea "**Última actualización:**" → fecha del día + "(Item 007 completo ✅)".
> - **No** marcar: el entregable "📋 `uv sync` + `uv run pytest` funcionando en Linux y Windows" (falta Windows → Item 009), el criterio de compatibilidad Python 3.14 en Windows (Item 008/009), las filas F3/F6 de la tabla de funcionalidades ni el estado de la Etapa 1 (se cierran al completar el Item 009).

## Próximo Paso

Item 007 completado (2026-09-07): `examples/config.{linux,windows}.json` (fieles a la visión, charset ISO8859_1, secretos `***`, ambos con exit 0 en `odin validate`), `examples/README.md`, subsección "Ejemplos de configuración" en el README principal, 5 fixtures nuevos en `tests/fixtures/` (`config_minimal`, `config_paths_relative`, `config_error_{types,ranges,missing}`) y `tests/test_fixtures.py` (16 casos; suite total 196).

Iniciar una **nueva sesión de chat** y ejecutar `/speckit.aide.create-item` con el número **008** (verificación de compatibilidad de dependencias con Python 3.14), luego `/speckit.aide.execute-item`.

**Nota para el Item 008:** los ejemplos y fixtures ya están listos para el smoke multiplataforma del Item 009 (`odin validate --config examples/config.<plataforma>.json`); falta confirmar la instalación de `paramiko`/`py7zr`/`apscheduler`/`pywin32` bajo Python 3.14 en Windows.

