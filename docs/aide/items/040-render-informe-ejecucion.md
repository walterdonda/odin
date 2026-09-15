# Item 040: Render del informe de ejecución (asunto y cuerpo en texto plano)

## Description

Implementar en `src/odin/notify.py` una función pura (sin SMTP) que construya el mensaje de correo desde `PipelineResult` + `Config`: asunto con estado global y hostname, y cuerpo en texto plano con el estado global (ÉXITO/PARCIAL/FALLO), el detalle por base (respaldo, compresión, transferencia y el error de la fase que falló), el detalle por servidor destino y los totales de duración y contadores. El texto final pasa por `SecretMasker.from_config(config)` como segunda barrera: el correo nunca incluye credenciales ni adjunta el backup.

## Acceptance Criteria

- [ ] `render_report(config, pipeline, *, log_tail=(), now=None, hostname=None)` (o equivalente documentado) devuelve asunto + cuerpo deterministas y testeables sin red.
- [ ] Asunto con estado global y hostname, p. ej. `[ODIN] PARCIAL — respaldo de <hostname> (<fecha>)`.
- [ ] Estado global: ÉXITO si todas las bases completaron las tres fases; PARCIAL si hubo mezcla; FALLO si falló todo, el lote no se ejecutó (`error_message`) o el lote está vacío.
- [ ] Cuerpo por base: respaldo (ruta, tamaño, duración), compresión (tamaño comprimido, duración) y el error de la fase fallida (`error_message`, `compression_error_message`, `transfer_error_message`).
- [ ] Cuerpo por servidor destino: `database → server: OK/FALLO` con motivo y bytes/duración.
- [ ] Totales de duración y contadores; casos borde cubiertos: sin servidores configurados, base sin transferencia, lote con `error_message`.
- [ ] El asunto y el cuerpo nunca contienen secretos de la configuración (doble barrera con `SecretMasker`) ni el backup adjunto.
- [ ] Si hay cola de log, se agrega al final del cuerpo bajo "Últimas líneas del log" (la captura es del Item 041; acá solo se renderiza lo recibido).
- [ ] Suite verde: `uv run pytest`, `uv run ruff check`, `uv run mypy`.

## Implementation Steps

1. Definir un contenedor inmutable del mensaje renderizado (p. ej. `ReportMessage(subject, body)`) junto a `NotificationResult`.
2. Derivar el estado global del `PipelineResult` (incluido `error_message` de lote y lote vacío).
3. Construir el asunto con estado, `hostname` (inyectable, default `socket.gethostname()`) y fecha (inyectable, default `datetime.now()`).
4. Construir el cuerpo por secciones: estado y resumen, por base, por servidor, totales y cola de log opcional.
5. Aplicar `SecretMasker.from_config(config).mask` al asunto y al cuerpo antes de devolver.
6. Documentar en el docstring la ausencia deliberada de adjuntos.

## Testing Strategy

- Tests de render en `tests/test_notify.py` (Item 042): estados ÉXITO/PARCIAL/FALLO, cifras por base y por servidor, sin servidores, lote fallido, cola de log incluida y ausencia de secretos con presencia de `***`.
- Cobertura de los casos borde con `PipelineResult` construidos a mano (sin ejecutar el pipeline real).
- Suite completa: `uv run pytest`, `uv run ruff check`, `uv run mypy`.

## Dependencies

- Item 039 (`src/odin/notify.py`), Item 035 (`PipelineResult`), `src/odin/log.py` (`SecretMasker`).

## Decisions & Trade-offs

- **Texto plano legible, sin HTML**: el informe se lee en cualquier cliente y en el log de correo; `EmailMessage.set_content` garantiza el `text/plain`.
- **`ReportMessage(subject, body)` como contrato** entre `render_report` (construcción pura) y `EmailNotifier.send` (transporte): el render no conoce `smtplib` y el notifier no conoce el pipeline; además hace triviales los tests de contenido.
- **Estado global derivado del lote final fusionado**: como `PipelineResult.backup.success` ya incorpora la transferencia (Item 035), la derivación no duplica la lógica de fases; `error_message` de lote y lote vacío fuerzan FALLO.
- **`now`/`hostname` inyectables** con defaults `datetime.now()`/`socket.gethostname()`: determinismo en tests sin monkeypatch.
- **Sección de cola de log solo si hay líneas**: `log_tail` vacío no imprime el encabezado "Últimas líneas del log"; el render no captura (eso es del Item 041) y se limita a volcar lo recibido.
- **Enmascarado del texto completo** (asunto + cuerpo, incluida la cola de log) con `SecretMasker.from_config`: segunda barrera independiente del handler del log; el correo nunca adjunta el backup ni incluye credenciales.
- **Base sin transferencia**: si no hay servidores configurados se informa `transferencia: no aplica (sin servidores)`; si hay servidores pero la base no llegó a transferir, la sección de destinos indica "sin transferencias en esta ejecución" sin inventar cifras.

**Evidencia:** `uv run ruff check src/odin` → All checks passed; `uv run mypy src/odin` → Success; smoke manual con `PipelineResult` mixto (base OK + base con compresión fallida, un destino, cola de log con `smtp-secret`) → asunto `[ODIN] PARCIAL — respaldo de srv01 (2026-09-15 10:00:00)`, secciones por base/destino/totales correctas y `smtp-secret` → `***` en la cola del cuerpo. Suite de contenidos formal en el Item 042.

## Prerequisites

- `docs/aide/progress.md` debe ser actualizado a 🚧 al iniciar.
- Al finalizar, actualizar `docs/aide/progress.md` a ✅.
