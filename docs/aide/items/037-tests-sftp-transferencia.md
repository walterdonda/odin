# Item 037: Tests de integración y unitarios para la transferencia SFTP

## Description

Completar la suite de tests de la Etapa 4 con dobles de `paramiko.SSHClient`/`SFTPClient` para los casos de éxito, fallo de autenticación, error de red con reintentos y verificación de tamaño fallida, y añadir un test de integración opcional contra un servidor sshd real (ephemeral, en proceso) que valide el flujo completo de conexión + upload + verificación.

## Acceptance Criteria

- [ ] Tests unitarios con mocks que cubren: upload exitoso con verificación de tamaño, verificación de tamaño fallida (como test propio y aislado), error de red reintentado hasta el éxito y hasta el agotamiento, autenticación por clave (carga de `RSAKey` con ruta y passphrase) y rechazo de claves PPK.
- [ ] Test de integración marcado `@pytest.mark.integration` contra un sshd ephemeral en proceso (paramiko `Transport` + `ServerInterface` + `SFTPServerInterface` sobre loopback) que valida upload + verificación reales, sin dependencias externas; con skip documentado si el entorno no lo permite.
- [ ] Se elimina el bloque de código muerto/desplazado dentro de `tests/test_transfer.py` (lógica de verificación de tamaño dentro de otro test).
- [ ] Suite completa verde: `uv run pytest`, `uv run ruff check`, `uv run mypy`.

## Implementation Steps

1. Revisar la cobertura existente (`tests/test_transfer.py`, `tests/test_transfer/test_retry_logic.py`, `tests/test_transfer_executor.py`) y listar los huecos.
2. Crear `tests/test_transfer_upload.py` (pytest style) con los casos unitarios que falten:
   - Reintento de `put` ante `OSError`/`SSHException` hasta el éxito.
   - Agotamiento de reintentos en `put` → error de transferencia con detalle.
   - Verificación de tamaño fallida → `TransferError` con "Integrity check failed" (test propio).
   - Auth por clave: `paramiko.RSAKey.from_private_key_file` invocado con ruta + passphrase; `.ppk` → `AuthenticationError` claro.
   - `close()` sin conexión previa no crashea (idempotente).
3. Corregir `tests/test_transfer.py`: mover el bloque de verificación de tamaño fuera de `test_upload_with_directory_creation` a un test dedicado.
4. Crear `tests/test_transfer_integration.py`: servidor SSH/SFTP ephemeral en un hilo (socket en `127.0.0.1` con puerto aleatorio, host key generada en memoria, `check_auth_password` fija, `SFTPServerInterface` con sistema de archivos en memoria o sobre `tmp_path`); ejecutar `TransferExecutor` contra él con política `accept-new` y verificar `TransferResult` exitoso con `transferred_bytes` correcto; caso de contraseña rechazada → `AuthenticationError` encapsulado en el resultado.
5. Ejecutar los tests de transferencia + suite completa y documentar resultados.

## Testing Strategy

- Los tests unitarios no hacen red: solo mocks/patch de `paramiko.SSHClient`/`SFTPClient` (patrón de `tests/test_transfer.py`).
- El test de integración usa un sshd real in-process sobre loopback: sin binarios externos, sin contenedores; se marca `integration` y queda estable para la suite completa.
- Comandos: `uv run pytest tests/test_transfer.py tests/test_transfer tests/test_transfer_upload.py tests/test_transfer_integration.py` y luego `uv run pytest` completo.

## Dependencies

- `src/odin/transfer.py` (Items 030-034), items 035-036 (pipeline y reporte), dependencia `paramiko`.

## Decisions & Trade-offs

- **`tests/test_transfer_upload.py` (pytest style) en lugar de extender el `unittest` de `tests/test_transfer.py`**: los huecos de la capa de upload (reintentos de `put`, agotamiento, verificación de tamaño como test propio, auth por clave, PPK, cierre idempotente) se agruparon en un archivo nuevo con el estilo mayoritario del repo; `tests/test_transfer.py` solo se corrigió (ver abajo).
- **Corrección de código muerto preexistente**: `tests/test_transfer.py::test_upload_with_directory_creation` contenía un bloque desplazado (sin `def`) que verificaba el tamaño erróneo dentro de otro test; se extrajo a `test_upload_integrity_failure` propio. La cobertura no cambia pero ahora falla/verde en el test correcto.
- **Integración con sshd ephemeral in-process** (`tests/test_transfer_integration.py`): en lugar de depender de un binario `sshd` o un contenedor (frágil en el entorno), se levanta un servidor SSH/SFTP real con `paramiko.Transport` en modo servidor sobre loopback (puerto aleatorio), host key RSA de 1024 generada en memoria, `ServerInterface` con `check_auth_password` fija y `SFTPServerInterface` respaldado por un directorio `tmp_path`. Se ejercita el flujo completo real: handshake, subsistema SFTP, upload, `stat` de verificación. Está marcado `@pytest.mark.integration` por semántica y **corre en la suite completa** porque no requiere servicios externos.
- **Detalle de paramiko 5.0 en el lado servidor**: `SFTPServerInterface.open()` debe devolver un `SFTPHandle` con `writefile` (la escritura la procesa el handle, no el método `write` de la interfaz), y `stat()` debe lanzar `OSError(SFTP_NO_SUCH_FILE)` para que el cliente dispare `mkdir` (así se ejercita la creación recursiva de directorios remotos). El cliente usa política `accept-new` porque la host key es efímera por test.
- **Coste aceptable**: `RSAKey.generate(1024)` por test (~1 s entre ambos casos); los backoffs del cliente se reducen (`0.001`) para no alargar la suite.
- **Auth por clave end-to-end**: para cerrar el criterio de demo de la Etapa 4 ("ambos métodos de autenticación ejercitados") se agregó `test_transfer_with_private_key_authentication`: par RSA generado en el test, `check_auth_publickey` por fingerprint en el servidor ephemeral y cliente con `auth.method = "key"` + `private_key` (PEM vía `write_private_key_file`; el `asbytes()` OpenSSH binario rompía el parseo del cliente). El flujo completo upload + verificación queda demostrado con los dos métodos.
- **Cierre idempotente**: `close()` sin conexión no crashea (garantía que ya usaba el `TransferExecutor` y quedó cubierta).

**Evidencia:** `uv run pytest -q` → 327 passed, 1 skipped (11 tests nuevos: 7 en `tests/test_transfer_upload.py`, 3 en `tests/test_transfer_integration.py`, 1 reestructurado en `tests/test_transfer.py`); `uv run ruff check src/odin tests` → All checks passed; `uv run mypy src/odin` → Success.

## Prerequisites

- `docs/aide/progress.md` debe ser actualizado a 📋 al iniciar.
- Al finalizar, actualizar `docs/aide/progress.md` a ✅.
