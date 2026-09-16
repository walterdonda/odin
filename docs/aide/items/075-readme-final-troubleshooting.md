# Item 075: README final con instalación, operación y troubleshooting

## Description

Reorganizar y completar `README.md` como **entrada única** del proyecto, de
modo que una persona que llega al repositorio pueda instalar, configurar,
operar y diagnosticar ODIN sin abrir el código. El README actual ya cubre
mucho (quickstart, ejemplos, validate, run, correo, retención, scheduler,
servicio, exit codes) pero le faltan: índice, requisitos explícitos de SO,
**instalación con `uv tool install`** (hoy prometida "para la Etapa 8"),
`--version`, sección de **logging**, **troubleshooting** y **licencia**; y la
introducción del modo servicio no debe duplicar `docs/service.md`.

Contenido requerido:

1. **Índice** navegable (anclas GitHub válidas).
2. **Requisitos**: SO soportados (Windows Server 2016+ / Linux LTS), Python
   ≥ 3.14 gestionado con `uv`, cliente Firebird del mayor correcto (`gbak`),
   conectividad (Firebird 3050/TCP, SFTP 22/TCP, SMTP) y permisos.
3. **Instalación**:
   - `uv tool install` desde el wheel construido (`uv build` →
     `uv tool install dist/odin-*.whl`) y desde el repositorio
     (`uv tool install .` / `uvx --from . odin`), con la ruta del script por
     plataforma (`~/.local/bin/odin`, `%USERPROFILE%\.local\bin\odin.exe`) y
     cómo actualizar/desinstalar (`uv tool upgrade odin`,
     `uv tool uninstall odin`).
   - Modo desarrollo: `uv sync` y `scripts/verify.py` (ya documentado en el
     quickstart; el índice debe enlazarlo).
4. **Configuración**: bloque por bloque (`databases`, `compression`, `servers`,
   `notification`, `local`, `scheduler`) con enlaces a `examples/`,
   `docs/firebird.md` y `docs/service.md`, y una tabla resumen de campos y
   defaults que consolide las tablas existentes (compression, notification,
   scheduler).
5. **Operación**: `validate` (`--strict`), `run`, `service
   run|status|reload|install|uninstall|start|stop`, `--version` con ejemplos,
   más la **tabla de exit codes** (ya existente, mantener como referencia
   única).
6. **Scheduler y modo servicio**: resumen breve con enlace a
   `docs/service.md` (sin duplicar la guía operativa).
7. **Logging** (`<resolved_log_dir>/odin.log`, rotación 5 MiB × 5, nivel
   configurable, enmascarado de secretos) y **retención local** (ya
   existente).
8. **Troubleshooting**: tabla problema → causa → solución con al menos los
   diez casos del item de cola: `gbak` no encontrado o versión equivocada →
   `gbak_path`; login Firebird / password de 2.5; permisos laxos del JSON;
   SMTP bloqueado o STARTTLS; host key SFTP estricta; cron/timezone
   inválidos; instalación del servicio sin permisos; cuenta del servicio sin
   acceso a rutas; `scheduler.enabled: false`; disco lleno en compresión.
9. **Seguridad**: resumen ejecutivo (JSON con credenciales legibles,
   `chmod 600`/ACL, auth SFTP por clave, host keys, enmascarado) con enlace a
   `docs/security.md` (Item 076, creado en este mismo lote).
10. **Integración continua** (ya existente) y **Licencia** (MIT según
    `pyproject.toml`).

Verificación antes de cerrar: cada comando documentado existe en `--help`
(`validate|run|service|service run|service status|service reload`), cada
enlace/ruta relativa del README existe en el árbol, y `odin validate` sigue
pasando sobre los dos ejemplos.

## Acceptance Criteria

- [ ] `README.md` abre con un **índice** cuyas anclas corresponden a las
      secciones reales (sin enlaces rotos).
- [ ] Sección **Requisitos** con SO soportados, Python ≥ 3.14 vía uv, `gbak`
      del mayor correcto y conectividad/permisos.
- [ ] Sección **Instalación** con `uv tool install` (wheel local y
      repositorio), `uvx`, ruta del script por plataforma y modo desarrollo
      (`uv sync` + `scripts/verify.py`).
- [ ] **Configuración** bloque por bloque con enlaces reales a `examples/`,
      `docs/firebird.md`, `docs/service.md` y tabla resumen de campos y
      defaults.
- [ ] **Operación** con ejemplos de `validate`, `run`, `service` y
      `--version`; tabla de **exit codes** vigente.
- [ ] **Scheduler/servicio** con enlace a `docs/service.md` y sin duplicar su
      contenido.
- [ ] **Logging** y **retención** documentados (rutas, rotación, nivel,
      enmascarado; política de retención).
- [ ] **Troubleshooting** con tabla problema → causa → solución y al menos los
      10 casos del item de cola.
- [ ] **Seguridad** con resumen y enlace a `docs/security.md`; **Licencia**
      MIT.
- [ ] Cada comando del README existe en `--help` y cada enlace/ruta es real
      (verificado con `grep`/rutas y `uv run odin ... --help`).
- [ ] Gates en verde: `uv run pytest` (al menos `tests/test_smoke.py`,
      `tests/test_cli.py`), `uv run ruff check src/odin tests`,
      `uv run mypy src/odin`, `uv run odin validate` sobre los dos ejemplos.
- [ ] Evidencia registrada en "Decisions & Trade-offs".

## Implementation Steps

1. Relevar los comandos reales (`uv run odin --help`, `validate --help`,
   `run --help`, `service --help` y acciones) y las tablas de defaults de
   `src/odin/config.py` para no documentar campos inexistentes.
2. Reescribir `README.md` con la estructura del punto 1 del Description:
   índice, requisitos, instalación (`uv tool install`/desarrollo),
   configuración (bloques + tabla resumen), operación y exit codes,
   scheduler/servicio (enlace), logging/retención, troubleshooting,
   seguridad (enlace), CI y licencia. Conservar las secciones ya correctas
   (correo, retención, scheduler, servicio, CI, compatibilidad 3.14) y
   moverlas bajo los encabezados nuevos sin perder contenido verificado.
3. Añadir la tabla de troubleshooting con los 10 casos.
4. Enlazar `docs/security.md` (Item 076) desde la sección de seguridad; si
   por orden de implementación el archivo aún no existe, crearlo en el mismo
   lote antes de cerrar (el enlace debe ser real).
5. Verificar comandos y enlaces: `uv run odin <cmd> --help`, chequeo de
   rutas relativas del README (`examples/`, `docs/*.md`, `scripts/`, `.github/`)
   y `uv run odin validate` sobre ambos ejemplos.
6. Correr los gates y actualizar `docs/aide/progress.md` (📋 → 🚧 → ✅) y este
   spec con decisiones/evidencia.

## Testing Strategy

- `uv run pytest tests/test_smoke.py tests/test_cli.py -q` → comportamiento
  de CLI documentado (versión, comandos, exit codes).
- `uv run odin validate --config examples/config.linux.json` y
  `.../config.windows.json` → los ejemplos siguen válidos (exit 0).
- Verificación de documentación: chequeo manual/asistido de que cada bloque
  ```bash``` con un comando `odin` corresponde a un subcomando/flag real de
  `--help` y de que cada enlace relativo resuelve en el árbol
  (`test -e <ruta>` / `grep`).
- Gates del repositorio: `uv run pytest`, `uv run ruff check src/odin tests`,
  `uv run mypy src/odin`.
- No se agregan tests automatizados de contenido del README (documentación);
  la verificación es la de los comandos y enlaces reales.

## Dependencies

- Items 071-074 (gate `scripts/verify.py`, CI y salvedades de Windows) ya ✅:
  el README debe reflejar su estado real.
- Item 076 (`docs/security.md`) del mismo lote: el enlace de la sección de
  seguridad debe apuntar a un archivo real.
- `docs/firebird.md` (Items 069/070) y `docs/service.md` (Items 067/074)
  existentes.
- `src/odin/config.py` como fuente de defaults para la tabla resumen.

## Decisions & Trade-offs

- **Reorganización por tareas, no reescritura**: se conservaron íntegras las
  secciones ya verificadas (correo, retención, scheduler, servicio, CI,
  compatibilidad 3.14, fases de `odin run`, garantías de `validate`) y se
  agregó la estructura de entrada única (índice, requisitos, instalación,
  configuración con tabla resumen, operación, logging, troubleshooting,
  seguridad, licencia). Las anclas del índice se contrastaron programáticamente
  contra los encabezados reales (0 rotas) y los enlaces relativos del README
  contra el árbol (0 rotos; solo `docs/security.md`, que crea el Item 076 de
  este mismo lote).
- **Tabla resumen de campos y defaults**: se consolidó con `src/odin/config.py`
  como fuente de verdad (`_parse_*`/dataclasses): p. ej. `compression.level` 7,
  `sftp_retries` 3 / `sftp_connect_timeout_sec` 30 (servidor y `local`),
  `operation_timeout` 60 s, backoff 2.0/30.0, `min_free_mb` 1024,
  `gbak_timeout_sec` 7200, `log_tail_lines` 50 y `retention_days` requerido
  (sin default). Se mantuvo además la tabla conductual del bloque `scheduler`
  en su sección (semántica de `skip_if_running`/`on_misfire`), porque el
  resumen no la reemplaza.
- **Instalación con `uv tool install`**: se documentaron los dos caminos
  reales (wheel construido con `uv build` y fuente del repositorio), la ruta
  del script por plataforma (`~/.local/bin`, `%USERPROFILE%\.local\bin`) con
  `uv tool update-shell`, la variante efímera `uvx --from . odin` y
  upgrade/uninstall. No se inventaron comandos: `--version` devuelve
  `odin 0.1.0` y los subcomandos citados existen en `--help` (verificado para
  los 10 comandos/acciones).
- **Troubleshooting con las 10 filas pedidas**: cada fila apunta a un
  comportamiento real del código (`gbak_path` y auto-detección, límite de 8
  bytes de Firebird 2.5, permisos del JSON de `validate`, SMTP/exit 1,
  `host_key_policy`, cron/timezone, permisos de instalación del servicio,
  cuenta del servicio, `scheduler.enabled`, `min_free_mb`/disco lleno).
- **Licencia**: el proyecto declara MIT en `pyproject.toml`; no existe un
  archivo `LICENSE` todavía (la metadata de release se revisa en el Item 077),
  así que la sección apunta al `pyproject.toml` en lugar de a un enlace
  inexistente.

**Evidencia:** `test -e` sobre cada ruta enlazada (solo faltaba
`docs/security.md`, del Item 076 en curso); chequeo de anclas del índice vs.
encabezados → 0 rotas; `uv run odin <validate|run|service|service
run|service status|service reload|service install|service uninstall|service
start|service stop> --help` y `uv run odin --version` → todos existen,
`odin 0.1.0`; `uv run odin validate --config examples/config.linux.json` →
exit 0 y `.../config.windows.json` → exit 0; `uv run pytest tests/test_smoke.py
tests/test_cli.py -q` → **96 passed**; `uv run ruff check src/odin tests` →
All checks passed; `uv run mypy src/odin` → Success 19 files. El enlace a
`docs/security.md` queda cubierto por el Item 076 del lote.

## Prerequisites

- **Servicios requeridos**: ninguno (trabajo de documentación); `uv` en el
  `PATH` para los gates.
- **Configuración de entorno**: ninguna variable obligatoria;
  `ODIN_BUILD_ARTIFACTS=1` no hace falta (no se reconstruye el wheel).
- **Checklist de validación manual**:
  - [ ] `uv run odin --version` → `odin 0.1.0`.
  - [ ] `uv run odin --help`, `validate --help`, `run --help`,
        `service --help` → todos los comandos citados existen.
  - [ ] `uv run odin validate --config examples/config.linux.json` → exit 0.
  - [ ] `uv run odin validate --config examples/config.windows.json` → exit 0.
  - [ ] Cada enlace relativo del README resuelve en el árbol.
- **Resultados esperados**: README como entrada única, sin enlaces ni
  comandos ficticios; troubleshooting con 10 filas; seguridad enlazada a
  `docs/security.md`.
- `docs/aide/progress.md` debe reflejar el avance (📋 → 🚧 → ✅) al completar.
- Al finalizar, actualizar `docs/aide/progress.md` con la evidencia del item
  (este README cierra parte del entregable "README" y de la guía de seguridad
  de la Etapa 8; la etapa completa no se marca hasta los Items 077/078).
