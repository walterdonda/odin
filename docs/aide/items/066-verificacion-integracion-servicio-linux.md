# Item 066: Verificación de integración del modo servicio Linux y runbook Windows

## Description

Crear `tests/test_service_linux_integration.py` (marcado
`@pytest.mark.integration`, skip seguro) con tres capas de verificación del
modo residente en Linux, más la constancia de lo que queda como procedimiento
manual por plataforma:

1. **Validación estructural de `deploy/odin.service`** (Item 060): secciones
   `[Unit]`/`[Service]`/`[Install]`, `Type=simple`, `ExecStart` absoluto con
   `service run --config`, `Restart=always`, `WantedBy=multi-user.target`. Si
   existe el binario `systemd-analyze`, se verifica **una unit renderizada**
   por `render_unit` con ejecutable real (sintaxis real de systemd) y se corre
   `systemd-analyze verify deploy/odin.service` solo cuando el binario de su
   `ExecStart` exista (hoy es un placeholder documentado: skip con motivo si
   no). Sin `systemd-analyze` → skip con motivo explícito.
2. **Ciclo de vida por la CLI real** (`odin service
   install|start|status|stop|uninstall`) con el gestor Linux real y el
   ejecutor de `systemctl` doble (inyectado con
   `monkeypatch.setattr("odin.cli.create_service_manager", ...)`): se afirma
   la secuencia exacta de comandos (`daemon-reload`/`enable` → `start` →
   `show` → `stop` → `stop`+`disable`+`daemon-reload`), los exit codes 0/1/2,
   la unit escrita con `ExecStart` absoluto y la salida de `status` compuesta
   (gestor + scheduler).
3. **Demo gated** (`ODIN_SERVICE_DEMO=1`, patrón del Item 057): con sesión
   systemd de usuario disponible (`systemctl --user is-system-running`) se
   instala una unit temporal en `~/.config/systemd/user/` con `Restart=always`
   y `ExecStart=<python> -m odin.cli service run --config <config acelerada>`
   sobre un `gbak` *stub* local (sin Firebird/SFTP; `servers: []`), se arranca,
   se verifica que un ciclo llega por el catcher SMTP (`tests/smtp_catcher.py`),
   se mata el proceso con `kill -9` y se comprueba que systemd lo **reinicia
   solo** (nuevo `MainPID`) y llega un segundo ciclo; limpieza de la unit al
   final. Skip-safe con motivo explícito si no hay systemd de usuario.

El docstring del test documenta qué parte del criterio de la Etapa 7 queda
como procedimiento manual (arranque en boot tras reinicio del SO) y que la
verificación en Windows Server real se ejecuta con el runbook de
`docs/service.md` en la Etapa 8 (Item 009).

## Acceptance Criteria

- [x] `tests/test_service_linux_integration.py` existe, está marcado
      `@pytest.mark.integration` y **no** falla en un host sin systemd
      (skips con motivo).
- [x] Capa 1: validación estructural de `deploy/odin.service` (secciones,
      `Type=simple`, `ExecStart` absoluto con `service run --config`,
      `Restart=always`, `WantedBy`); `systemd-analyze verify` de una unit
      renderizada con ejecutable real cuando el binario existe, y del archivo
      de referencia solo si su `ExecStart` apunta a un binario existente.
- [x] Capa 2: la CLI real recorre `install → start → status → stop →
      uninstall` con el gestor real y un `systemctl` doble, afirmando la
      secuencia exacta de comandos, los exit codes (0 y 1 en el fallo del
      gestor) y que la unit escrita usa rutas absolutas.
- [x] Capa 3 (gated): con `ODIN_SERVICE_DEMO=1` y sesión systemd de usuario,
      una unit temporal con `Restart=always` arranca `odin service run`, llega
      un ciclo al catcher SMTP, `kill -9` provoca el reinicio automático de
      systemd (MainPID nuevo) y un segundo ciclo; la unit se limpia al final.
- [x] La demo documenta en su docstring que el arranque en boot y Windows
      Server real quedan como verificación manual (runbook de
      `docs/service.md`, Etapa 8/Item 009).
- [x] `uv run pytest tests/test_service_linux_integration.py -q` pasa (con
      skips explícitos por defecto) y la variante
      `ODIN_SERVICE_DEMO=1 uv run pytest tests/test_service_linux_integration.py -q`
      ejecuta la demo real cuando el host la soporta.
- [x] Gates del item en verde: `uv run pytest tests/test_service_linux_integration.py`,
      `uv run ruff check src/odin tests`, `uv run mypy src/odin`.

## Implementation Steps

1. Escribir `tests/test_service_linux_integration.py` con las tres capas y el
   docstring de alcance/delegaciones.
2. Capa 1: parser mínimo del archivo de referencia + `render_unit` real +
   `systemd-analyze` vía `shutil.which` (skip si falta).
3. Capa 2: `_write_config` (fixture Linux mutado a `work_dir`/logs temporales)
   y un `FakeSystemctl` con respuestas por comando; monkeypatch de
   `odin.cli.create_service_manager`; recorrido de la CLI con `main([...])`.
4. Capa 3: helper de sesión de usuario (`systemctl --user`), config acelerada
   con `gbak` stub (`#!/bin/sh` que escribe el `.fbk`), unit temporal,
   catcher SMTP, `kill -9`, espera de `MainPID` nuevo y segundo correo,
   limpieza en `finally`.
5. Correr los gates del item y documentar decisiones/evidencia.

## Testing Strategy

- `uv run pytest tests/test_service_linux_integration.py -q` (por defecto:
  capas 1 y 2 verdes, demo saltada con motivo).
- Estructural: asserts de texto sobre la unit de referencia y verify real
  cuando el host tiene `systemd-analyze`.
- CLI: aserciones sobre la lista de comandos registrada por el doble en cada
  acción y sobre los mensajes/exit codes de `main`.
- Demo gated: correo ÉXITO por ciclo (asunto `[ODIN] ÉXITO`, base OK,
  sin secretos), `MainPID` distinto tras `kill -9`, estado final del
  scheduler con el pid del proceso reiniciado.
- Sin red externa: SMTP es el catcher in-process y el único destino de las
  fases es un `gbak` stub local.

## Dependencies

- Item 060 (`render_unit`, `LinuxServiceManager`, `deploy/odin.service`),
  Item 062 (CLI del ciclo de vida), Item 063 (`status` compuesto).
- Item 065 (`ServiceRunner` real detrás de `odin service run`) y Item 057
  (patrón de demo gated y catcher SMTP) / Item 047 (`tests/smtp_catcher.py`).
- Insumos: `queue-007.md` (Lote C) y `docs/aide/roadmap.md` (Etapa 7).

## Decisions & Trade-offs

- **Verify de la unit de referencia con skip por placeholder**:
  `systemd-analyze verify deploy/odin.service` devuelve error mientras
  `/opt/odin/bin/odin` no exista (el `ExecStart` versionado es un placeholder
  documentado). En vez de tolerar el error del binario ausente, el test salta
  ese verify con motivo explícito y **siempre** verifica una unit renderizada
  por `render_unit` con un ejecutable real: cubre la sintaxis de systemd sobre
  el mismo formato que genera el gestor, sin depender de una instalación real.
- **Capa 2 con el gestor real y el ejecutor doble**: se monkeypatchea
  `odin.cli.create_service_manager` (nombre resuelto en el módulo CLI) para
  construir un `LinuxServiceManager` real con `unit_dir` temporal, `runner`
  doble y `can_write_unit=True`; así se ejercita la CLI, el render de la unit
  y el mapeo de `status`, sin tocar `systemctl` ni el systemd del host. Las
  acciones `start|stop|uninstall` sin `--config` construyen el gestor con el
  centinela absoluto de la CLI (no leen el JSON, como en producción).
- **La demo corre `sys.executable -m odin.cli`**, no el `odin` del PATH: el
  gestor systemd de usuario no hereda el PATH del shell, y el venv del
  proyecto (instalación editable) garantiza que `odin` sea importable. La unit
  demo se escribe a mano —no con `render_unit`— porque `render_unit` no admite
  `-m odin.cli` (su contrato es `<ejecutable> service run --config <ruta>`);
  replica `Type=simple`, `Restart=always` y `RestartSec=1`.
- **Config con `gbak` stub y `servers: []`**: el stub (`/bin/sh` que escribe
  el `.fbk` de salida) permite ciclos ÉXITO sin Firebird, y sin servidores la
  fase de transferencia se considera satisfecha; el único externo es el
  catcher SMTP in-process. Así la demo verifica el ciclo completo real
  (scheduler → pipeline → correo) y no solo el arranque del proceso.
- **Detección del segundo ciclo contando mensajes posteriores al `kill -9`**:
  se captura el conteo justo después de matar el proceso, de modo que el
  segundo correo solo puede venir del proceso reiniciado; además se exige
  `MainPID` nuevo antes de esperarlo. Deadlines de 150 s por la granularidad
  de un minuto del cron `* * * * *`.
- **Skip-safe por capas**: sin `systemd-analyze` se saltan los verify; sin
  sesión `systemctl --user` operativa la demo se salta con motivo; sin
  `ODIN_SERVICE_DEMO=1` ni siquiera se intenta. La limpieza de la unit temporal
  (`stop`, `reset-failed`, borrado, `daemon-reload`) corre en `finally`.
- **Alcance explícito**: el arranque en boot (reinicio del SO) queda como
  procedimiento manual documentado y Windows Server real se verifica con el
  runbook de `docs/service.md` en la Etapa 8 (Item 009); acá Windows se cubre
  con los dobles de `win32serviceutil` (Item 061) y el runner del Item 065.

**Evidencia:** `uv run pytest tests/test_service_linux_integration.py -q` →
**4 passed + 2 skipped** (verify de la referencia saltado por placeholder,
demo gated saltada por defecto); con `ODIN_SERVICE_DEMO=1 uv run pytest
tests/test_service_linux_integration.py::test_user_service_restarts_after_kill_and_delivers_cycles
-q` → **1 passed in 77.66 s** (sesión systemd de usuario real: ciclo ÉXITO,
`kill -9` del MainPID, mainpid nuevo con `Restart=always` y segundo ciclo
ÉXITO; unit temporal limpiada, sin unidades residuales en
`~/.config/systemd/user`); `uv run ruff check src/odin tests` → All checks
passed; `uv run mypy src/odin` → Success: no issues found in 19 source files.

## Prerequisites

- Requiere Linux con systemd **solo** para la demo gated; las capas 1 y 2
  corren en cualquier Linux (la 1 salta `systemd-analyze` si falta).
- La demo necesita sesión `systemctl --user` operativa y el paquete `odin`
  instalado en el intérprete (`sys.executable -m odin.cli`), más
  `ODIN_SERVICE_DEMO=1`.
- No requiere Firebird, SFTP ni SMTP externo (stub `gbak` + catcher local).
- `docs/aide/progress.md` debe reflejar el avance (📋 → 🚧 → ✅) al completar.
- Al finalizar, actualizar `docs/aide/progress.md` con la evidencia del item.
