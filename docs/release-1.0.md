# Release 1.0.0 — criterios de éxito verificados

> **Etapa 8 / Item 078.** Cierre formal de la etapa: verificación uno a uno de
> los ocho criterios de éxito de `docs/aide/vision.md` §9 sobre la release
> `1.0.0` (Item 077), con evidencia ejecutada y salvedades explícitas. El
> entorno de cierre es Linux (Python 3.14.4, uv 0.11.17, Docker 29.7.2) sin
> remoto publicado ni host Windows: las corridas reales de Windows quedan
> delegadas al job `windows` de la CI o al runbook de `docs/service.md` §8,
> igual que en las Etapas 5 y 7.

**Fecha de cierre:** 2026-09-16.

## Resumen

| # | Criterio | Estado | Evidencia principal | Salvedad |
|---|---|---|---|---|
| 1 | Instalación `uv tool install` en limpio | ✅ | Wheel `1.0.0` + tool install aislado; contenedor `ubuntu:24.04` | Windows Server real vía CI/runbook |
| 2 | Punta a punta con Firebird 2.5 y 5/6 | ✅ | Matriz 5 versiones (3/3 restore) + e2e con `.fbk`/`.fbk.7z` y correo | Casilla de correo externa real |
| 3 | Tolerancia a fallos | ✅ | Reintentos agotados + parcial con exit 3 | — |
| 4 | Notificación de error y exit codes | ✅ | Correo FALLO + exit 4; SMTP caído no crashea | — |
| 5 | Validación (`odin validate`) | ✅ | 54 tests de validate + `field_path` por campo | — |
| 6 | Seguridad: logs/correo sin secretos | ✅ | Tests de ausencia sobre logs, stdout y SMTP real | — |
| 7 | Calidad: suite + documentación | ✅ | `verify.py` 6/6; 652 passed + 8 skipped; ruff + mypy | — |
| 8 | Modo servicio residente | ✅ | Demo systemd con auto-recuperación; ciclo de vida Windows con dobles | Windows Server real vía CI/runbook |

---

## 1. Instalación

`uv tool install` funciona sin pasos manuales en un Linux LTS limpio y la vía
de Windows queda preparada y delegada.

- **Linux — instalación aislada del wheel**: `ODIN_BUILD_ARTIFACTS=1 uv run
  pytest tests/test_packaging.py -q` → **4 passed in 9.33 s** (Item 077):
  `uv build` (wheel/sdist `1.0.0`), `uv tool install` con
  `UV_TOOL_DIR`/`UV_TOOL_BIN_DIR`/`HOME` temporales, `odin --version` →
  `odin 1.0.0`, `odin validate` de los dos ejemplos y `odin service status`
  (exit 0, "Servicio del SO" no instalado).
- **Linux — contenedor limpio**: `uv run pytest
  tests/test_packaging_integration.py -q` → 1 passed + 1 skipped (capa
  `ubuntu:24.04` con el wheel copiado, Item 072); la variante e2e gated
  `ODIN_CLEAN_CONTAINER_E2E=1` → 2 passed con `odin run` completo.
- **Windows Server**: job `windows` de `.github/workflows/ci.yml` (mismo gate
  `scripts/verify.py`, `uv sync --locked`, `uv build` + artefacto) y runbook
  de `docs/service.md` §8. La primera corrida real completa los campos de
  `docs/service.md` §9.2.

**Salvedad:** no hay Windows Server en este entorno; no se declara verificada
una corrida que no ocurrió. La confirmación runtime de `pywin32`/Python 3.14
en Windows la aporta esa primera corrida (CI o runbook).

## 2. Punta a punta

Una ejecución completa produce el `.fbk`, lo comprime a `.fbk.7z`, lo deposita
en los destinos SFTP y envía el correo con el resumen.

- **Firebird real, extremos 2.5 y 5/6**: `uv run pytest
  tests/test_firebird_matrix.py -q -m integration -s` → **5 passed in
  23.31 s** (Items 069/070): 2.5.9 (`gbak` LI-V2.5.9.27139, UTF8, `.fbk`
  2560 B), 3.0.9, 4.0.5, 5.0.4 (LI-V5.0.4.1812, `.fbk` 1536 B) y
  6.0-snapshot, todos con **3/3 filas restauradas** a base scratch con el
  `gbak` de la misma familia. Las filas 2.5/5.0 vuelven a correr dentro de la
  suite completa del cierre (Docker disponible, sin skips).
- **Pipeline completo**: `tests/test_notify_integration.py` (2 passed) y el
  e2e del contenedor limpio con Firebird 5.0 de la matriz + sshd ephemeral +
  catcher SMTP (Item 072, gated `ODIN_CLEAN_CONTAINER_E2E=1` → 2 passed):
  `.fbk` > 0, `.fbk.7z` > 0 y correo `[ODIN] ÉXITO` con el resumen.
- **Firebird 6.x**: solo existe build *snapshot* (`6-snapshot`); la fila es
  *best-effort* y la guía `docs/firebird.md` §7 recomienda esperar una release
  estable para producción.

**Salvedad:** el envío a una **casilla de correo externa real** no es
verificable en este entorno (sin acceso a un servidor SMTP de Internet ni a
una casilla de control); la entrega se verifica contra el catcher SMTP
in-process con el mensaje SMTP real, mismo criterio que la Etapa 5. En
despliegue, la casilla de control recibe el informe real.

## 3. Tolerancia a fallos

Un servidor SFTP caído no aborta la ejecución: se agotan los reintentos
configurados, los demás destinos continúan y el informe refleja el estado
parcial.

- `tests/test_transfer_executor.py::test_retries_exhausted_before_continuing_with_next_server`
  (2 intentos al caído y el siguiente servidor completa).
- `tests/test_cli.py::test_run_partial_transfer_failure_exits_3` (exit 3).
- `tests/test_notify.py::test_render_partial_state` (el informe detalla el
  destino fallido) y aislamiento por base en `tests/test_pipeline.py`.

## 4. Notificación de error y exit codes

Ante fallos de `gbak`, compresión o destinos, el proceso termina con exit
code ≠ 0, deja el error en el log y envía el correo de fallo; un SMTP caído no
hace crashear el proceso.

- `tests/test_cli.py::test_run_total_failure_exits_4` (exit 4) y
  `tests/test_pipeline.py::test_total_failure_still_sends_report` (correo
  FALLO).
- SMTP caído: exit 0 degrada a 1 con entrada en `odin.log`, sin traceback
  (`tests/test_notify_integration.py`, puerto cerrado, Item 047).
- Matriz de exit codes vigente (0/3/4/2/1) en el README y en
  `src/odin/cli.py` (`EXIT_OK`/`EXIT_CONFIG`/`EXIT_INTERNAL`/`EXIT_PARTIAL`/
  `EXIT_FAILED`).

## 5. Validación

`odin validate` detecta y describe errores de estructura, tipos, rangos y
rutas antes de ejecutar, con `field_path` por campo y severidades
ERROR/WARNING.

- `tests/test_validate.py` → **54 passed** (Item 076); `tests/test_config.py`
  (parseo con campo/motivo) y `tests/test_fixtures.py` (fixtures de error con
  `field_path` específico, Item 007).
- `uv run odin validate --config examples/config.linux.json` y
  `.../config.windows.json` → exit 0 (paso del gate `scripts/verify.py`).

## 6. Seguridad: ningún log ni correo con credenciales

- `tests/test_transfer_masking.py` (3 tests): ausencia de secretos y presencia
  de `***` sobre stdout/stderr de `odin run` real y `odin.log` real.
- `tests/test_notify.py::test_render_never_includes_secrets` y
  `tests/test_notify_integration.py` (mensaje SMTP real sin secretos).
- `tests/test_log.py` (enmascarado de logs) y el estado del scheduler
  (`tests/test_scheduler_state.py`).
- Guía completa de amenazas, permisos, claves y límites en
  `docs/security.md`, enlazada desde README y `docs/service.md`.

## 7. Calidad

- **Gates**: `uv run python scripts/verify.py` → **EXIT 0** (6/6 pasos:
  sync, pytest 73.77 s, ruff, mypy, validate Linux y Windows).
- **Suite**: `uv run pytest -q` → **652 passed + 8 skipped** (los 8 skips son
  los gated documentados: build de artefactos, e2e del contenedor, demo de
  cadencia real, demos systemd/service y SCM de Windows).
- **Lint y tipado**: `uv run ruff check src/odin tests` → All checks passed;
  `uv run mypy src/odin` → Success 19 files.
- **Documentación**: `README.md` como entrada única, `docs/firebird.md`,
  `docs/security.md`, `docs/service.md`, `CHANGELOG.md` y specs AIDE;
  consistencia verificada (ver más abajo).

## 8. Modo servicio residente

ODIN corre como servicio con scheduler propio (sin cron ni Task Scheduler),
dispara según el JSON, se recupera tras caídas y no duplica bases.

- **Linux**: demo gated `ODIN_SERVICE_DEMO=1` con unit de usuario real →
  **1 passed in 102.27 s** (Item 068): ciclo ÉXITO por el catcher SMTP,
  `kill -9` al proceso, systemd lo reinicia solo (MainPID nuevo) y corre el
  segundo ciclo. La demo de cadencia real (`ODIN_FOREGROUND_DEMO=1`, cron
  `* * * * *`) ejecutó 2 ciclos en 78.6 s (Item 057).
- **Windows**: ciclo de vida completo con dobles de `pywin32` (31 tests:
  arranque automático, failure actions `SC_ACTION_RESTART`, stop limpio,
  uninstall idempotente) más el escenario real del SCM gated
  `ODIN_WINDOWS_SERVICE_SMOKE=1` en el job `windows` de la CI.
- **Solapamiento**: `tests/test_scheduler.py` (reserva atómica por base,
  `skip_if_running` ambos valores y misfire con reloj falso) — un job en
  ejecución no duplica el respaldo de la misma base.

**Salvedad:** el reinicio del **SO** en Windows Server real y la corrida real
del SCM en CI/runbook están pendientes de la primera ejecución sobre Windows
(`docs/service.md` §9.2), mismo criterio que la Etapa 7.

---

## Consistencia documental (2026-09-16)

- **Enlaces y anclas**: chequeo programático de `README.md`, `CHANGELOG.md` y
  `docs/*.md` (rutas relativas + anclas GitHub) → **0 rotos**.
- **Comandos**: 12 invocaciones `odin` distintas citadas en esos documentos,
  contrastadas contra `--help` → **todas existen** (`--version`, `--help`,
  `validate`, `run` y `service run|status|reload|install|uninstall|start|stop`).
- **Ejemplos**: `odin validate` sobre `examples/config.linux.json` y
  `examples/config.windows.json` → exit 0.
- **Versiones coherentes**: `1.0.0` en `pyproject.toml`, `uv.lock`,
  `src/odin/__init__.py`, `CHANGELOG.md` y las dos menciones del README; sin
  restos de `0.1.0` en fuentes, tests ni documentación de producto (los
  registros históricos de AIDE conservan la evidencia de la versión de
  entonces). El tag anotado `v1.0.0` queda pendiente de crear tras el commit
  de la release (la sesión de batch no crea commits).
- **Guía de seguridad enlazada** desde el README (secciones de configuración,
  troubleshooting y seguridad) y desde `docs/service.md` §1/§3/§4.

## Gates finales ejecutados

| Gate | Comando | Resultado |
|---|---|---|
| Gate único del proyecto | `uv run python scripts/verify.py` | EXIT 0 — 6/6 pasos |
| Suite completa | `uv run pytest -q` | 652 passed + 8 skipped (79.53 s) |
| Lint | `uv run ruff check src/odin tests` | All checks passed |
| Tipado | `uv run mypy src/odin` | Success 19 files |
| Empaquetado + instalación aislada | `ODIN_BUILD_ARTIFACTS=1 uv run pytest tests/test_packaging.py -q` | 4 passed (9.33 s) |
| Versión instalada | `uv run odin --version` | `odin 1.0.0` |
| Consistencia documental | enlaces/anclas + comandos vs `--help` | 0 rotos / 12 comandos OK |

## Salvedades de plataforma

1. **Windows Server real** (criterios 1 y 8): la verificación runtime del SCM,
   el reinicio del SO y `uv tool install` en un host limpio se ejecutan por el
   job `windows` de la CI (se activa al publicar el repositorio) o por el
   runbook `docs/service.md` §8; los campos a completar están en §9.2.
2. **Casilla de correo externa real** (criterio 2): la entrega se verifica
   contra el catcher SMTP in-process con mensaje real; el envío a Internet no
   es verificable en este entorno.
3. **Firebird 6.x**: solo hay build *snapshot*; la matriz lo cubre como
   *best-effort*.
4. **Tag `v1.0.0`**: pendiente de crear sobre el commit de la release; comando
   en `docs/aide/items/077-release-1-0-0.md`.

Estas salvedades no afectan la funcionalidad entregada: están aisladas en las
corridas que requieren un host/red que este entorno no tiene, y quedan
documentadas con su procedimiento de cierre.
