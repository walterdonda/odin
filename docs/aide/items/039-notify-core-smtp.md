# Item 039: Implementación core de `src/odin/notify.py` (cliente SMTP con STARTTLS/SSL)

## Description

Implementar el cliente SMTP de ODIN sobre `smtplib` (solo stdlib): envía el informe de ejecución a `notification.to` desde `notification.from_` usando `notification.smtp` (`host`, `port`, `starttls`, `username`, `password`), con STARTTLS por defecto, modo plano para relays locales y SSL implícito (puerto 465) vía el nuevo campo opcional `smtp.ssl`. Los timeouts de conexión/operación son parametrizables con default sensato inline (30 s), sin extender el JSON. Los errores operativos esperados no se propagan: se reportan en `NotificationResult` y se loguean sin exponer credenciales.

## Acceptance Criteria

- [ ] `src/odin/notify.py` define `NotificationResult` (frozen dataclass: `success`, `duration_seconds`, `error_message`, destinatario) y `EmailNotifier` con `from_config(config)` y `send(...)`; el módulo expone `__all__` y docstring.
- [ ] Transporte: STARTTLS cuando `smtp.starttls: true` (default); SMTP plano cuando `starttls: false`; SSL implícito cuando `smtp.ssl: true`.
- [ ] `config.SmtpConfig` gana `ssl: bool = False`; `_SMTP_FIELDS` lo acepta; `smtp.ssl: true` con `starttls: true` es error de configuración con `field_path` claro.
- [ ] `SMTPException`, `OSError` y `socket.timeout` (y subclases como `ConnectionRefusedError`) no se propagan: quedan como `success=False` con mensaje legible; el log no expone credenciales.
- [ ] Éxito → `NotificationResult(success=True, duration_seconds=...)` con el destinatario configurado.
- [ ] `examples/config.linux.json` y `examples/config.windows.json` incluyen `"ssl": false` y la documentación (README y `examples/README.md`) menciona el campo.
- [ ] Suite verde: `uv run pytest`, `uv run ruff check`, `uv run mypy`.

## Implementation Steps

1. Crear `src/odin/notify.py` (solo `smtplib`, `socket`, `time`, `dataclasses`, stdlib) con `DEFAULT_SMTP_TIMEOUT_SEC = 30`.
2. Definir `NotificationResult` con `recipient` (destinatario) y `EmailNotifier(smtp, to, from_, timeout=DEFAULT_SMTP_TIMEOUT_SEC)` + `from_config(config)`.
3. Implementar `send(...)`: elegir `SMTP_SSL` si `smtp.ssl`, si no `SMTP`; `starttls()` tras `ehlo()` cuando `starttls`; `login()` solo con `username` no vacío; `send_message` con `EmailMessage` (`From`/`To`/`Subject`).
4. Capturar los errores esperados en un `NotificationResult` fallido (con duración) y loguear vía `odin.log.logger`; no capturar errores de programación.
5. Agregar `ssl: bool = False` a `SmtpConfig`, `"ssl"` a `_SMTP_FIELDS`, parseo en `_parse_smtp` y validación de exclusión mutua con `starttls: true`.
6. Ajustar `validate._check_notification`: con `ssl: true` no advertir por `starttls: false` (el canal ya va cifrado).
7. Actualizar ejemplos (`ssl: false`) y documentación mínima del campo en README/`examples/README.md`.

## Testing Strategy

- Tests unitarios con `unittest.mock` de `smtplib.SMTP`/`SMTP_SSL` (Item 042): selección de transporte, STARTTLS, login, envelope y errores.
- Parseo de `smtp.ssl` y exclusión mutua en `tests/test_config.py` (Item 042).
- Suite completa: `uv run pytest`, `uv run ruff check`, `uv run mypy`.

## Dependencies

- `src/odin/config.py` (Item 002), `src/odin/log.py` (Item 004), `src/odin/validate.py` (Item 006).

## Decisions & Trade-offs

- **`smtplib` puro (stdlib)**: no suma dependencias; cubre STARTTLS, SSL implícito, `login` y `send_message` sin capa extra.
- **`smtp.ssl` mutuamente excluyente con `starttls: true`**: se valida en `_parse_smtp` y el problema apunta a `config.notification.smtp.ssl` (no al `starttls` default). SSL implícito no negocia STARTTLS sobre un canal ya cifrado; permitir ambos sería ambiguo. Como `starttls` default es `true`, usar SSL exige escribir explícitamente `"starttls": false`.
- **Timeout inline (30 s)**: `DEFAULT_SMTP_TIMEOUT_SEC` sin extender el JSON; si la operación real pide otro valor, se inyecta por constructor (los tests lo usan).
- **Errores esperados encapsulados**: se capturan `smtplib.SMTPException` y `OSError` (que cubre `socket.timeout`/`TimeoutError` y `ConnectionRefusedError`). El mensaje incluye host, puerto y `tipo: detalle`; las credenciales nunca se interpolan y el `MaskingFilter` de los handlers da la segunda barrera sobre cualquier secreto indirecto.
- **Cierre best-effort**: `quit()` fallido solo deja un `warning`; no convierte un envío exitoso en fallo ni oculta el error original.
- **`send(report: ReportMessage)`**: el notifier recibe el mensaje ya renderizado (Item 040) y arma el `EmailMessage` con `From`/`To`/`Subject`; sin adjuntos por diseño.
- **`validate._check_notification`**: con `smtp.ssl: true` ya no advierte por `starttls: false` (el canal va cifrado); la verificación OK indica el transporte efectivo.
- **Tests diferidos al Item 042**: por el agrupamiento del lote, la suite de `smtplib` mockeado y el parseo de `ssl` viven en `tests/test_notify.py`/`tests/test_config.py` (Item 042); en este item la verificación es ruff + mypy + suite existente + parseo manual y `odin validate` de los ejemplos.

**Evidencia:** `uv run ruff check src/odin tests` → All checks passed; `uv run mypy src/odin` → Success (12 archivos); `uv run pytest tests/test_config.py tests/test_validate.py tests/test_fixtures.py tests/test_log.py -q` → 138 passed; parseo verificado con config temporal: `ssl: true` + `starttls` default → `config.notification.smtp.ssl` en problemas, `ssl: true` + `starttls: false` → carga OK, default → `ssl=False`; `uv run odin validate --config examples/config.linux.json` → exit 0 con `(STARTTLS)` en `config.notification.to`.

## Prerequisites

- `docs/aide/progress.md` debe ser actualizado a 🚧 al iniciar.
- Al finalizar, actualizar `docs/aide/progress.md` a ✅.
