# Item 047: Test de integración con servidor SMTP efímero in-process

## Description

Crear `tests/test_notify_integration.py` (marcado `@pytest.mark.integration`) con un servidor SMTP mínimo in-process sobre loopback y puerto efímero implementado con la stdlib (`socketserver.ThreadingTCPServer`): saludo `220`, `EHLO` con `AUTH LOGIN`, `MAIL FROM`/`RCPT TO`/`DATA` y captura del mensaje entregado. Los casos de `odin run` usan dobles de respaldo y transferencia (los dos bordes con procesos/red externos), compresión real local (py7zr) y notificación real (`EmailNotifier` sin doblar) contra el catcher: es el sustituto local de "correo recibido en la casilla de control" del criterio de aceptación de la Etapa 5. La variante opcional con Firebird real por Docker (patrón del Item 018) queda skip-safe: corre el flujo `gbak + 7z + correo` punta a punta contra el catcher solo cuando Docker, su daemon y `gbak` están disponibles.

## Acceptance Criteria

- [ ] `tests/test_notify_integration.py` define un catcher SMTP stdlib (`socketserver`) sobre `127.0.0.1` con puerto efímero, y registra mensajes, remitentes, destinatarios y credenciales de `AUTH LOGIN`.
- [ ] `odin run` con dobles de respaldo/transferencia, compresión real y `EmailNotifier` real: el catcher recibe `RCPT TO:<notification.to>` y un único mensaje con `To`/`From`/`Subject` del informe, estado `ÉXITO`, la base con `OK`, el servidor destino con `OK`, los totales y la cola de log (Item 041) en el cuerpo.
- [ ] `AUTH LOGIN` se ejercita con el usuario/contraseña de `notification.smtp` (registrado por el catcher) y el `odin run` termina en exit code 0.
- [ ] Ausencia de secretos en el mensaje recibido: contraseñas de base (`masterkey`), SFTP (`remote-secret-1`) y SMTP (`smtp-secret`) no aparecen en el texto entregado.
- [ ] Puerto cerrado (conexión rechazada): `odin run` devuelve exit code 1 (matrix del Item 044), no crashea, imprime `Correo NO enviado:` en stderr y deja la entrada en `odin.log`.
- [ ] Variante Firebird real: `odin run` sin dobles (gbak + 7z + correo reales) contra el contenedor Docker del Item 018 genera el `.fbk.7z` y el catcher recibe el informe `ÉXITO`; se salta sin fallo si Docker, su daemon o `gbak` no están disponibles.
- [ ] Suite verde: `uv run pytest`, `uv run ruff check`, `uv run mypy`.

## Implementation Steps

1. Crear `tests/test_notify_integration.py` con docstring de módulo (enfoque del sshd ephemeral del Item 037), fixtures autouse de limpieza del logger `odin` y de aislamiento de `ODIN_CONFIG`.
2. Implementar `_SmtpCatcher` (`ThreadingTCPServer` en 127.0.0.1:0, hilo daemon, `close()` con shutdown/join) y `_SmtpHandler` con las respuestas del protocolo (`220`, `EHLO` multilínea con `AUTH LOGIN`, `AUTH LOGIN` con respuesta inicial o por desafío, `MAIL`/`RCPT`/`DATA`, `QUIT`).
3. Implementar el helper `_write_config(tmp_path, *, smtp_port, starttls=False, servers=1, retention_days=0, log_tail_lines=5)` que copia el fixture Linux y apunta `notification.smtp` al catcher.
4. Implementar los dobles locales `_FakeBackupExecutor` (escribe `.fbk` reales en el `work_dir`), `_FakeTransferExecutor` (éxito verificando el tamaño local) y `_FakeRetentionExecutor` (no-op deshabilitado); la compresión queda real (`py7zr`) para que el informe muestre tamaños/datos de artefactos verdaderos.
5. Test de éxito: `main(["run", ...])` + catcher; asserts de destinatario, cuerpo, AUTH, exit code, ausencia de secretos y `catcher.errors == []`.
6. Test de puerto cerrado: obtener un puerto libre cerrándolo, config apuntando ahí, asserts de exit code 1, stderr y `odin.log`.
7. Test opcional Firebird: reutilizar el patrón Docker del Item 018 (probe de disponibilidad con `BackupExecutor` y retry), `servers=[]`, `retention_days=0`, comparar `to` contra el mensaje y verificar el `.fbk.7z` en `work_dir`.

## Testing Strategy

- `uv run pytest tests/test_notify_integration.py -q` (los dos primeros tests corren siempre; el de Firebird se salta sin Docker/gbak).
- Verificación manual de evidencia: `uv run pytest tests/test_notify_integration.py -v` mostrando el skip declarado del Firebird.
- Gates: `uv run pytest`, `uv run ruff check`, `uv run mypy`.

## Dependencies

- Items 039-046 (`EmailNotifier`/`render_report`, `capture_log_tail`, pipeline completo y patrón de dobles de `tests/test_cli.py`).
- Item 018 (patrón Docker/gbak del test de integración de respaldo), usado solo por la variante opcional.

## Decisions & Trade-offs

- **Compresión real, no doblada**: el doble de compresión obligaría a fabricar `CompressionResult`/artefactos falsos; py7zr es local, determinista y rápido, así que la compresión corre de verdad y el informe expone tamaños y duraciones reales. Los dobles quedan donde hay procesos externos (gbak) y red (SFTP), que es lo que la suite no puede garantizar.
- **`AUTH LOGIN` con respuesta inicial**: `smtplib` envía `AUTH LOGIN <b64(usuario)>` (RFC 4954); el handler también soporta el modo por desafío para robustez ante cambios de `smtplib`.
- **Puerto cerrado por socket efímero**: se reserva y cierra un puerto loopback para gatillar `ConnectionRefusedError` de forma determinista e inmediata (sin depender de timeouts).
- **Firebird skip-safe en dos niveles**: `skipif` por binarios + `pytest.skip` si el contenedor no arranca o el puerto no se publica; el probe con `BackupExecutor` reintenta hasta 60 s para no depender de la carrera de arranque del contenedor.
- **Sin TLS en el catcher**: se prueba el transporte plano (`starttls: false`), el camino que ya cubre `odin run` local; STARTTLS/SSL están cubiertos con dobles en `tests/test_notify.py` (montar TLS real exigiría certificados y no aporta al criterio de la casilla de control).

**Evidencia:** `uv run pytest tests/test_notify_integration.py -v` → **2 passed + 1 skipped** (la variante Firebird se salta con `gbak no instalado en el host`): el caso de éxito entrega con `EmailNotifier` real (sin doblar) contra el catcher y verifica `MAIL FROM:<odin-backups@example.com>`, `RCPT TO:<control@example.com>`, `AUTH LOGIN` con `smtp-user`/`smtp-secret`, asunto `[ODIN] ÉXITO`, cuerpo con base/servidor/totales/cola de log y ausencia de `masterkey`, `remote-secret-1` y `smtp-secret`; el caso de conexión rechazada devuelve exit 1 sin crash con `Correo NO enviado: ... ConnectionRefusedError` en stderr y `Correo NO enviado` en `odin.log`. `uv run ruff check tests/test_notify_integration.py` → All checks passed; `uv run mypy src/odin` → Success (13 source files).

## Prerequisites

- `docs/aide/progress.md` debe ser actualizado a 🚧 al iniciar.
- Al finalizar, actualizar `docs/aide/progress.md` a ✅.
