# Item 034: Aislamiento de fallos por servidor y `TransferResult`

## Description

Implementar un ejecutor de transferencias que recorra la lista de servidores destino, aislando los fallos: si un servidor falla tras agotar reintentos, se registra el error y se continúa con el siguiente. Definir el dataclass `TransferResult` para reportar el estado (éxito/fallo), tamaño transferido, duración y mensaje de error por servidor.

## Acceptance Criteria

- [x] Implementación de un ejecutor de transferencias en `src/odin/transfer.py`.
- [x] El ejecutor debe iterar sobre todos los servidores configurados sin detenerse ante fallos individuales.
- [x] Definición del dataclass `TransferResult` con los campos: estado, tamaño transferido, duración y mensaje de error.
- [x] Implementación de tests unitarios para el ejecutor y el dataclass.

## Implementation Steps

1. Definir el dataclass `TransferResult` en `src/odin/transfer.py`.
2. Implementar la función o clase `TransferExecutor` que recorra la lista de servidores.
3. Asegurar que cada iteración capture las excepciones y las encapsule en un `TransferResult`.
4. Integrar la lógica de reintentos (del Item 033) dentro de este ejecutor.
5. Implementar tests unitarios que simulen una lista de servidores donde algunos fallan y otros tienen éxito.

## Testing Strategy

- Unit tests: Mock de la lógica de transferencia individual para simular una lista de servidores donde:
    - Servidor 1: Éxito.
    - Servator 2: Fallo (después de reintentos).
    - Servidor 3: Éxito.
- Verificar que el resultado final sea una lista/colección de `TransferResult` que incluya tanto éxitos como fallos.
- Verificar que el proceso no se detiene tras el fallo del Servidor 2.

## Dependencies

- `src/odin/transfer.py` (desarrollo en paralelo con Item 030-033).

## Decisions & Trade-offs

- **`TransferResult` inmutable con `success: bool`**: sigue el patrón de `BackupResult` (Etapa 2) y `CompressionResult` (Etapa 3) — estado booleano + mensaje de error opcional — en lugar de un enum de estado. Incluye `server_name`, `local_path`, `remote_path`, `transferred_bytes`, `duration_seconds` y `error_message`: los cuatro campos que exige el item (estado, tamaño, duración, error) más los identificadores que necesitarán el resumen del pipeline y el correo (items 035-036).
- **`TransferExecutor.run_batch_transfer()` devuelve `list[TransferResult]`** (uno por servidor, en el orden de la configuración), no un `BatchTransferResult`: el criterio pide una colección de resultados y el agregado con totales queda para el Item 036. El ejecutor no propaga excepciones: cada fallo se encapsula en el resultado de su servidor.
- **Integración de reintentos**: `_build_transfer()` reenvía a `SFTPTransfer` los cinco parámetros de `ServerConfig` (`sftp_retries`, `sftp_connect_timeout_sec`, `sftp_operation_timeout_sec`, `sftp_retry_backoff_base`, `sftp_retry_max_delay_sec`) y la política de host keys (`host_key_policy.value`). Los reintentos siguen viviendo en `SFTPTransfer._execute_with_retry` (Item 033); el ejecutor solo recibe el `ConnectionError` final tras agotarlos.
- **Cierre garantizado**: `close()` se invoca en `finally` aunque `connect()`/`upload()` fallen, y un fallo al cerrar solo se registra como advertencia para no enmascarar el error original.
- **Archivo local inexistente**: se detecta antes de conectar; el resultado es un fallo claro por destino sin abrir conexiones (ningún servidor puede tener éxito con un origen ausente) y sin consumir reintentos.
- **Correcciones de integración detectadas al ejecutar el item** (necesarias para que el ejecutor funcione de verdad):
  - `_execute_with_retry` reintentaba `paramiko.AuthenticationException` cuando el mensaje no contenía "authentication" (p. ej. "Auth failed"), degradando el fallo de auth a `ConnectionError` tras agotar los reintentos. Ahora se re-lanza de inmediato y `connect()` la mapea a `AuthenticationError` (el test preexistente `test_connect_auth_failure` queda en verde).
  - `_set_policy` usaba `set_missing_hostkey_policy`, que no existe en paramiko 5.0 (el método real es `set_missing_host_key_policy`): toda conexión `strict`/`accept-new`/`insecure` habría fallado con `AttributeError`. Se corrigió el nombre y los tests que lo verificaban.
  - `transfer.py` y sus tests quedaron limpios de ruff/mypy (el módulo tenía 27 errores de lint y 12 de mypy, y la suite 1 test rojo); se retiró un test muerto y se acortaron los backoffs de prueba (suite completa: 295 verdes + 1 skip en ~5 s).

**Pendientes/puntos futuros** (fuera del alcance del Item 034):

- `_parse_server()` acepta `sftp_retries`, `sftp_connect_timeout_sec` y `sftp_operation_timeout_sec` en el JSON pero no los asigna a `ServerConfig` (y no acepta los dos parámetros de backoff), así que hoy rigen los defaults del dataclass. Cablear esos campos al parseo corresponde al cierre de los items 030/033.
- La autenticación por clave usa `paramiko.RSAKey` (solo claves RSA); soportar Ed25519/ECDSA queda como mejora futura.
- `BatchTransferResult` con totales y su cableado al pipeline/correo quedan en los items 035-036.

## Prerequisites

- `docs/aide/progress.md` debe ser actualizado a 📋 al iniciar.
- Al finalizar, actualizar `docs/aide/progress.md` a ✅.
