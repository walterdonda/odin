# Item 030: Conexión paramiko con autenticación por password y clave privada

## Description

Implementar la lógica base de conexión SSH/SFTP utilizando `paramiko`. Soporte para autenticación mediante contraseña (`password`) y clave privada (`key`), permitiendo el uso de rutas con `~` y manejo de `passphrase` opcional. El módulo debe reportar errores de conexión o de autenticación de forma clara sin exponer credenciales.

## Acceptance Criteria

- [ ] Implementación de `src/odin/transfer.py`.
- [ ] Soporte para autenticación por `password`.
- [ ] Soporte para autenticación por `key` (ruta con `~` soportada).
- [ ] Soporte para `passphrase` en claves privadas.
- [ ] Manejo de errores de conexión y autenticación sin exponer credenciales en logs.
- [ ] Implementación de tests unitarios con mocks de `paramiko`.

## Implementation Steps

1. Crear el módulo `src/odin/transfer.py`.
2. Implementar la lógica de resolución de rutas para la clave privada (usando `paths.py`).
3. Implementar la función core de conexión SSH/SFTP usando `paramiko.SSHClient`.
4. Implementar el manejo de autenticación según la configuración disponible.
5. Asegurar que los errores se capturen y se reporten mediante un mecanismo que no loguee secretos.
6. Implementar tests unitarios en `tests/test_transfer.py`.

## Testing Strategy

- Unit tests: Mock de `paramiko.SSHClient` y `paramiko.SFTPClient` para simular:
    - Conexión exitosa con password.
    - Conexión exitosa con clave privada.
    - Fallo de autenticación (password incorrecto).
    - Fallo de autenticación (clave incorrecta).
    - Error de red (timeout).
- Verificar que las rutas con `~` se resuelven correctamente antes de pasar a `paramiko`.

## Dependencies

- `paramiko`
- `src/odin/paths.py`
- `src/odin/log.py` (para asegurar el enmascarado)

## Decisions & Trade-offs

To be updated during implementation.

## Prerequisites

- `docs/aide/progress.md` debe ser actualizado a 📋 al iniciar.
- Al finalizar, actualizar `docs/aide/progress.md` a ✅.
