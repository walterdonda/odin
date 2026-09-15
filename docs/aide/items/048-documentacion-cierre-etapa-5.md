# Item 048: Documentación y cierre de la Etapa 5

## Description

Cerrar la Etapa 5 con documentación y verificación. Actualizar `README.md` con la sección **"Notificación por correo"** (config SMTP con `host`/`port`/`starttls`/`ssl`/`username`/`password`, `log_tail_lines`, contenido del informe, correo solo texto que nunca adjunta el backup ni incluye secretos, y comportamiento ante SMTP caído con su efecto en el exit code) y la sección **"Retención local"** (`retention_days`, qué archivos elimina, frontera de antigüedad y protección de la corrida actual, política de fallo que no altera el exit code). Ajustar la descripción de `odin run` y la coherencia de `examples/README.md`. Revisar docstrings módulo a módulo: retirar de `cli.py` (docstring de `build_parser`) la promesa de "cuando lleguen la compresión/transferencia/correo" ya implementadas, y pulir el anuncio del enmascarado de `log.py`. Verificar explícitamente los criterios de aceptación de la Etapa 5 del roadmap con evidencia (tests y salidas), correr los gates completos y dejar `docs/aide/progress.md` con la Etapa 5 ✅ (F5, G4 y criterios marcados), `docs/service.md` no aplica aún (Etapa 7).

## Acceptance Criteria

- [ ] `README.md` trae la sección "Notificación por correo" con: estructura `notification` (SMTP `host`/`port`/`starttls`/`ssl`/`username`/`password` y `log_tail_lines`), modos de transporte (STARTTLS default, plano, SSL implícito y su exclusión mutua), contenido del informe (estado, por base, por servidor, totales y cola de log), garantía "solo texto, sin adjuntos, sin secretos" y comportamiento ante SMTP caído (log + exit code 1 en corrida por lo demás exitosa).
- [ ] `README.md` trae la sección "Retención local" con: `local.retention_days`, convención de nombres gestionados (`<nombre_bd>_<timestamp>.fbk[.7z]`), frontera estricta de antigüedad, protección de los artefactos de la corrida, `0` = deshabilitado y política de fallo (no altera el exit code).
- [ ] `odin run` descrito con la secuencia completa (respaldo → compresión → transferencia → correo → retención) y `examples/README.md` coherente (tabla de exit codes final y campos consumidos).
- [ ] Docstrings revisados: `cli.py` (`build_parser`) sin referencias a etapas futuras ya implementadas; `log.py` describe el enmascarado como implementado; sin promesas obsoletas en el resto de los módulos.
- [ ] Criterios de aceptación de la Etapa 5 verificados uno a uno con evidencia en "Decisions & Trade-offs" (test/archivo:línea y resultado).
- [ ] Gates en verde: `uv run pytest`, `uv run ruff check src/odin tests`, `uv run mypy src/odin`.
- [ ] `docs/aide/progress.md`: Etapa 5 → ✅, F5 → ✅, G4 → ✅, criterios marcados con evidencia, "Última actualización" y "Próximo Paso" (nueva sesión + `/speckit.aide.create-queue` para la Etapa 6, queue-005 agotada).

## Implementation Steps

1. Reorganizar la sección de `odin run` del README: pasos 1-3 (gbak), 4 (compresión), 5 (transferencia), 6 (correo) y 7 (retención), con punteros a las secciones detalladas.
2. Agregar `## Notificación por correo` y `## Retención local` con el bloque JSON de ejemplo y la tabla de comportamiento.
3. Actualizar `examples/README.md`: tabla de exit codes final, descripción de `odin run` completa y nota final de campos consumidos.
4. Corregir el docstring de `build_parser` en `src/odin/cli.py` y el de `src/odin/log.py`; revisar `notify.py`, `retention.py`, `pipeline.py`, `config.py`, `validate.py`.
5. Verificar criterios de la Etapa 5 ejecutando los tests citados y registrando resultado/evidencia.
6. Correr los gates completos y actualizar `docs/aide/progress.md`.

## Testing Strategy

- Gates completos: `uv run pytest`, `uv run ruff check src/odin tests`, `uv run mypy src/odin`.
- Evidencia por criterio de la Etapa 5:
  - End-to-end con correo recibido → `tests/test_notify_integration.py` (catcher local, sustituto de la casilla de control) + Item 047.
  - Destino caído → PARCIAL + exit 3 → tests de pipeline/CLI de transferencia parcial + notificación (`tests/test_cli.py::test_run_partial_with_notification_failure_exits_3`, `tests/test_pipeline.py`).
  - Fallo de gbak → FALLO + exit 4 → `tests/test_pipeline.py::test_total_failure_still_sends_report`, CLI de fallo total.
  - Enmascarado sin credenciales → `tests/test_transfer_masking.py`, `tests/test_notify.py::test_render_never_includes_secrets`, `tests/test_notify_integration.py`.
- Verificación de documentación: `uv run odin run --help` menciona el correo (test `test_run_help_mentions_email`).

## Dependencies

- Items 039-047 (todo lo que se documenta y cierra).

## Decisions & Trade-offs

- **`docs/service.md` queda fuera**: pertenece a la Etapa 7; no se crea acá para no adelantar documentación sin implementación.
- **Verificación con evidencia local**: el criterio "correo recibido en la casilla de control" se acredita con el catcher SMTP in-process del Item 047 (mismo criterio que el sshd ephemeral del Item 037), no con una casilla externa; la variante Firebird con Docker refuerza el punta a punta cuando el host lo permite.
- **Reorganización mínima del README**: se conserva el texto existente donde sigue siendo correcto (compresión, transferencia, matriz de exit codes del Item 044) y se agregan las dos secciones nuevas, evitando reescribir documentación ya verificada.
- **`examples/README.md` también se ajusta**: estaba stale desde la Etapa 2 (tabla de exit codes sin correo y "ejecuta la fase de respaldo"); la coherencia documental entra en el alcance del cierre.

**Evidencia:** Verificación criterio a criterio de la Etapa 5 del roadmap:

- **End-to-end con correo recibido**: `uv run pytest tests/test_notify_integration.py -q` → 2 passed + 1 skipped (la variante Firebird se salta por `gbak no instalado en el host`); el informe llega íntegro al catcher SMTP local (sustituto de la casilla de control): estado `ÉXITO`, base y servidor OK, totales y cola de log, sin secretos.
- **Destino caído → PARCIAL + exit 3**: `uv run pytest tests/test_cli.py::test_run_partial_transfer_failure_exits_3 tests/test_notify.py::test_render_partial_state -q` → 2 passed (el render del estado PARCIAL detalla el servidor fallido).
- **Fallo de gbak → FALLO + exit 4**: `uv run pytest tests/test_cli.py::test_run_total_failure_exits_4 tests/test_pipeline.py::test_total_failure_still_sends_report -q` → 2 passed (el informe de FALLO se envía igual y el exit code es 4).
- **Enmascarado sin credenciales**: `uv run pytest tests/test_notify.py::test_render_never_includes_secrets tests/test_transfer_masking.py -q` → 4 passed (correo y logs sin secretos).

Documentación y gates: `README.md` con "Notificación por correo" (tabla de `notification`/`notification.smtp` incluido `ssl`, contenido, seguridad y SMTP caído), "Retención local" (`retention_days`, convención gestionada, protección de la corrida y política de fallo) y `odin run` como ciclo one-shot de 7 pasos; `examples/README.md` con la tabla de exit codes final y los campos consumidos; docstrings de `cli.py` (`build_parser`), `log.py` y `validate.py` alineados sin promesas de etapas ya implementadas. `uv run pytest` → **410 passed + 2 skipped**; `uv run ruff check src/odin tests` → All checks passed; `uv run mypy src/odin` → Success (13 source files).

## Prerequisites

- `docs/aide/progress.md` debe ser actualizado a 🚧 al iniciar.
- Al finalizar, actualizar `docs/aide/progress.md` a ✅.
