# Item 042: Tests unitarios de notificación con mock de `smtplib`

## Description

Suite `tests/test_notify.py` con `unittest.mock` de `smtplib.SMTP`/`smtplib.SMTP_SSL` y de `socket`, más las ampliaciones de `tests/test_config.py` para `smtp.ssl`. Cubre el transporte del Item 039 y el render del Item 040 (incluida la cola de log del Item 041), con verificación de ausencia de secretos.

## Acceptance Criteria

- [ ] STARTTLS invocado solo cuando corresponde (y `ehlo` correspondiente); modos plano y SSL.
- [ ] `login` con usuario/contraseña; envelope correcto (`from`/`to`).
- [ ] Timeouts propagados como fallo en `NotificationResult` sin excepción.
- [ ] `SMTPAuthenticationError`, `SMTPConnectError` y `ConnectionRefusedError` → resultado fallido con mensaje claro; `send_message` fallido → resultado fallido; éxito → `success=True` con duración.
- [ ] Render por estado ÉXITO/PARCIAL/FALLO, cifras por base y servidor, caso sin servidores y lote fallido (`error_message`), y base sin transferencia.
- [ ] Ausencia de secretos (contraseñas de BD/SFTP/SMTP y rutas de claves) en asunto y cuerpo, con presencia de `***`.
- [ ] Inclusión de la cola de log cuando está configurada/recibida.
- [ ] `tests/test_config.py`: parseo de `smtp.ssl` y exclusión mutua con `starttls: true`.
- [ ] Suite verde: `uv run pytest`, `uv run ruff check`, `uv run mypy`.

## Implementation Steps

1. Crear `tests/test_notify.py` con una config real en `tmp_path` (patrón de `tests/test_pipeline.py`/`tests/test_cli.py`) y helpers para `PipelineResult`.
2. Tests de transporte con `monkeypatch.setattr("odin.notify.smtplib.SMTP", ...)`/`SMTP_SSL`: selección de clase, `starttls`, `login`, `send_message` y envelope.
3. Tests de errores: `socket.timeout`/`TimeoutError`, `SMTPAuthenticationError`, `SMTPConnectError`, `ConnectionRefusedError` y fallo de `send_message`.
4. Tests de render: los tres estados, cifras, sin servidores, lote con `error_message`, base sin transferencia y cola de log.
5. Test de ausencia de secretos: inyectar secretos distintivos (≥ 4 caracteres) en mensajes de error y verificar `secret not in asunto + cuerpo` y `MASK` presente.
6. Ampliar `tests/test_config.py` con el parseo de `ssl`, el default `false` y la exclusión mutua.
7. Ejecutar la suite completa y los gates de calidad.

## Testing Strategy

- Dobles de `smtplib` con `unittest.mock.MagicMock`/clases falsas que registran llamadas; sin red real.
- Render con `PipelineResult` construidos a mano; fechas/hostname inyectados para determinismo.
- Verificación por ausencia y presencia explícita, patrón del Item 038.
- Suite completa: `uv run pytest`, `uv run ruff check`, `uv run mypy`.

## Dependencies

- Items 039, 040 y 041.

## Decisions & Trade-offs

- **Dobles de clase en lugar de `MagicMock`**: `FakeSMTP`/`FakeSMTPSSL` registran el orden exacto de `ehlo`/`starttls`/`login`/`send_message`/`quit` y permiten inyectar fallos por atributo de clase (`connect_exception`, `login_exception`, `send_exception`); más legible que encadenar `mock.assert_has_calls` y cubre el envelope real leyendo el `EmailMessage` recibido.
- **Parcheo de `smtplib.SMTP`/`SMTP_SSL` con `monkeypatch`** (atributos del módulo, que `odin.notify` resuelve en cada `send`): sin red real y con restauración automática; el fixture resetea además el estado de clase para aislar tests.
- **`test_login_skipped_without_username` construye `SmtpConfig` directo**: el parser exige `username`/`password` no vacíos, así que el caso "sin credenciales" solo es representable a nivel de dataclass (documenta ese contrato del parseo).
- **Render con `PipelineResult` construido a mano** (patrón de `tests/test_pipeline.py`) y `now`/`hostname` inyectados: asunto exacto y determinista sin monkeypatch ni reloj real.
- **Test de secretos con los valores reales de la fixture**, incluida la ruta normalizada de `private_key` (los secretos se leen del `Config` cargado, no hardcodeados): verifica ausencia de cada uno y presencia de `***` en asunto+cuerpo con la cola de log incluida.
- **Parseo de `smtp.ssl`**: default `false`, combinación válida con `starttls: false` y error de exclusión mutua con `starttls: true` apuntando a `config.notification.smtp.ssl`.

**Evidencia:** `uv run ruff check src/odin tests` → All checks passed; `uv run mypy src/odin` → Success; `uv run pytest tests/test_notify.py tests/test_config.py tests/test_log.py -q` → 105 passed (22 tests nuevos en `tests/test_notify.py` — 12 de transporte y 10 de render — + 3 de `smtp.ssl` en `tests/test_config.py`).

## Prerequisites

- `docs/aide/progress.md` debe ser actualizado a 🚧 al iniciar.
- Al finalizar, actualizar `docs/aide/progress.md` a ✅.
