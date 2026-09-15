# Item 067: Documentación operativa `docs/service.md` y README del modo residente

## Description

Escribir `docs/service.md`, la guía operativa del modo servicio residente de
ODIN (Etapa 7), y actualizar `README.md` para que el modo residente tenga su
sección, la matriz por plataforma y el enlace a la guía.

`docs/service.md` debe cubrir, contrastado contra el código real (Items
059-066):

- **Visión general**: el scheduler interno del bloque `scheduler` del JSON más
  el servicio residente del SO; sin cron ni Task Scheduler.
- **Windows**: `odin service install|uninstall|start|stop|status` con permisos
  de administrador; arranque automático; reinicio ante caída (failure actions
  del SCM a `restart_delay_seconds`); cuenta de servicio y sus accesos a la
  config/`work_dir`/`gbak`/red; actualización de la config y recarga con
  `odin service reload` vía archivo de control; evento/registro del SCM.
- **Linux**: contenido y ubicación de `deploy/odin.service`;
  `systemctl daemon-reload && systemctl enable --now odin`; decisión root vs
  usuario del servicio; permisos del JSON; `odin service reload` por `SIGUSR1`
  o archivo de control.
- **Lectura de `odin service status`**: encabezado del gestor + sección del
  scheduler, estados posibles y sugerencias.
- **Log**: ubicación `<resolved_log_dir>/odin.log` y rotación (5 MiB × 5
  backups), sin consola en modo residente.
- **Diagnóstico de fallos comunes**: config relativa o `scheduler.enabled:
  false`; cuenta del servicio sin acceso a rutas Firebird/`gbak`; timezone;
  salida SMTP/SFTP bloqueada; `systemctl` rechazando la unit.
- **Desinstalación limpia** en ambas plataformas.
- **Runbook de verificación en Windows Server real** (instalar → arrancar →
  reiniciar el SO → matar el proceso → confirmar recuperación automática →
  `status`), a ejecutar en la Etapa 8 (Item 009).

Actualizar `README.md`: sección del modo servicio con los comandos nuevos y la
matriz por plataforma, tabla de exit codes ampliada y enlace a
`docs/service.md`; ajustar el docstring/ayuda de la CLI si quedara alguna
mención a "Etapa 7" como trabajo futuro.

## Acceptance Criteria

- [x] `docs/service.md` existe y contiene: visión general; operación Windows
      (comandos, permisos, arranque automático, reinicio ante caída, cuenta,
      accesos, recarga, registro del SCM); operación Linux (unit de referencia,
      `daemon-reload`/`enable --now`, root vs usuario, permisos del JSON,
      recarga); lectura de `status`; ubicación y rotación del log; diagnóstico
      de los fallos comunes listados; desinstalación limpia en ambas
      plataformas; runbook de Windows Server real.
- [x] Cada afirmación operativa coincide con el comportamiento implementado
      (`src/odin/service/{base,linux,windows,runner}.py`, `src/odin/cli.py`,
      `src/odin/log.py`): rutas, comandos, defaults (`auto_start=True`,
      `restart_delay_seconds=5`, log 5 MiB × 5), exit codes y modos de recarga.
- [x] `README.md` tiene una sección de modo servicio con los comandos
      `install|uninstall|start|stop|status|reload`, la matriz por plataforma y
      el enlace a `docs/service.md`; la tabla de exit codes refleja las
      acciones del modo residente.
- [x] Ninguna mención a "Etapa 7" como trabajo futuro en el docstring/ayuda de
      la CLI; si existe, se corrige.
- [x] Gates en verde: `uv run pytest`, `uv run ruff check src/odin tests`,
      `uv run mypy src/odin`.

## Implementation Steps

1. Leer los módulos del modo servicio (`base.py`, `linux.py`, `windows.py`,
   `runner.py`), `cli.py` (parser y handlers `_cmd_service_*`), `log.py` y
   `deploy/odin.service` para redactar con el comportamiento real.
2. Escribir `docs/service.md` con todas las secciones del item.
3. Actualizar `README.md` (sección del modo servicio, matriz por plataforma,
   tabla de exit codes, enlace a la guía).
4. Revisar el docstring de `cli.py` y la ayuda del parser: eliminar cualquier
   mención a "Etapa 7" futura.
5. Correr los gates y documentar decisiones/evidencia.

## Testing Strategy

- `grep` de cobertura temática sobre `docs/service.md` (Windows, Linux,
  `systemctl`, `SIGUSR1`, `scheduler_reload.request`, log, diagnóstico,
  desinstalación, runbook) y sobre `README.md` (comandos y enlace).
- Verificación de exactitud: contrastar cada comando/ruta/default contra el
  código citado; sin afirmar nada que el código no haga (p. ej. la cuenta de
  servicio del CLI es la default de la plataforma; `restart_on_failure` no se
  expone como flag del CLI).
- Gates completos del batch.

## Dependencies

- Items 059-066 (toda la superficie del modo residente: contrato, gestores
  Linux/Windows, CLI del ciclo de vida, `status` compuesto, logging sin
  consola, runner compartido y verificación de integración).
- `docs/aide/queue/queue-007.md` (Lote D) y `docs/aide/roadmap.md` (Etapa 7).
- Item 066: su docstring delega explícitamente el arranque en boot y Windows
  Server real al runbook de `docs/service.md`; el runbook debe existir acá.

## Decisions & Trade-offs

- **Documentación derivada del código, no de la descripción de la cola**: cada
  afirmación se contrastó contra la implementación real —
  `LinuxServiceManager` (unit en `/etc/systemd/system/odin.service`, install
  escribe + `daemon-reload` + `enable` pero **no arranca**, guía textual sin
  permisos, uninstall idempotente),
  `WindowsServiceManager` (`InstallService` con `SERVICE_AUTO_START`, failure
  actions de reinicio a los `restart_delay_seconds` y reset 24 h,
  `SetServiceCustomOption` para config/working dir, host de pywin32),
  `ServiceRunner` (logging residente sin consola con stdio redirigido, recarga
  `SIGUSR1`/archivo de control) y `log.py` (5 MiB × 5 en
  `<resolved_log_dir>/odin.log`) — en vez de repetir la intención del item.
- **Cuenta de servicio: se documenta el límite real.** La CLI **no expone** un
  flag de cuenta (el parser solo acepta `--config`), así que la guía explica
  que `install` usa la cuenta por defecto de la plataforma (root/LocalSystem) y
  que una cuenta dedicada se configura editando la unit (`User=`/`Group=`) o el
  host de pywin32/`ServiceSpec.account` para uso programático. Inventar un flag
  inexistente habría dejado la guía mintiendo.
- **Ejemplos de `odin service status` con salida real**: el bloque "no
  instalado + sin estado" es la salida literal del comando sobre
  `examples/config.linux.json`; el bloque "en ejecución" se generó con los
  renderizadores reales (`render_platform_status` + `render_service_status`) y
  un estado de ejemplo, para no publicar un formato inventado (los valores de
  `CycleStatus` se muestran como los emite el estado: `success`, etc.).
- **README con sección propia y matriz por plataforma**: se agregó "Modo
  servicio residente" antes de "Exit codes", con la tabla Linux/Windows
  (gestor, permisos, arranque en boot, reinicio, recarga, estado y log) y el
  enlace a `docs/service.md`; la tabla de exit codes ahora incluye
  `install|uninstall|start|stop`. La frase que anunciaba la documentación
  "con el Item 009" se corrigió para apuntar a la guía operativa.
- **Sin cambios de código**: el docstring de `cli.py` ya describía
  `install|uninstall|start|stop` y no quedaba ninguna mención a la Etapa 7 como
  trabajo futuro en la ayuda; el único texto que la nombra (`cli.py:410`) la usa
  como contexto del modo residente, no como promesa.

**Evidencia:** `docs/service.md` (371 líneas) cubre visión general, Windows
(instalación/permisos/tareas/cuenta/recarga/eventos), Linux
(unit/`daemon-reload`/`enable`/root vs usuario/permisos/recarga),
`odin service status` con salidas reales, log y rotación, diagnóstico de los
fallos comunes pedidos, desinstalación limpia y el runbook de Windows Server;
`grep -c` sobre el archivo da 12 `systemd`, 14 `systemctl`, 3 `SIGUSR1`, 2
`scheduler_reload.request`, 8 `odin.log`. `README.md`: 2 enlaces a
`docs/service.md`, 6 apariciones de `service install`, sección nueva y tabla de
exit codes ampliada. Gates: `uv run pytest -q` → **623 passed + 5 skipped**;
`uv run ruff check src/odin tests` → All checks passed; `uv run mypy src/odin`
→ Success: no issues found in 19 source files.

## Prerequisites

- No requiere servicios externos: es documentación y revisión.
- `docs/aide/progress.md` debe reflejar el avance (📋 → 🚧 → ✅) al completar.
- Al finalizar, actualizar `docs/aide/progress.md` con la evidencia del item.
