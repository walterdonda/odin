# Item 032: Creación recursiva de directorios remotos y upload con verificación

## Description

Añadir la funcionalidad de crear directorios de forma recursiva en el servidor remoto si no existen antes de iniciar la transferencia. Tras el upload de cada `.fbk.7z`, realizar una verificación post-transferencia comparando el tamaño del archivo local contra el `stat` remoto para garantizar la integridad.

## Acceptance Criteria

- [ ] Implementación de la creación recursiva de directorios en `src/odin/transfer.py`.
- [ ] Implementación de la verificación de tamaño post-transferencia (local vs remoto).
- [ ] El proceso de transferencia no falla si el directorio remoto ya existe.
- [ ] Integración en el flujo de transferencia de archivos.
- [ ] Implementación de tests unitarios con mocks de `paramiko.SFTPClient`.

## Implementation Steps

1. Implementar método `_ensure_remote_dir_exists(sftp, remote_path)` en `src/odin/transfer.py`.
2. Implementar método `_verify_transfer_integrity(sftp, remote_path, local_size)` en `src/odin/transfer.py`.
3. Integrar estas verificaciones en la lógica principal de transferencia de archivos.
4. Implementar tests para la creación de directorios y para la verificación de tamaño.

## Testing Strategy

- Unit tests: Mock de `paramiko.SFTPClient.mkdir`, `paramiko.SFTPClient.stat` y `paramiko.SFTPClient.putsf`:
    - Caso de éxito: directorio existe, transferencia completa, tamaño coincide.
    - Caso de directorio necesario: directorio no existe, se crea, se transfiere.
    - Caso de error de integridad: tamaño remoto != tamaño local, se reporta error.
    - Caso de error de permisos en creación de directorio.

## Dependencies

- `src/odin/transfer.py` (desarumento con Item 030).

## Decisions & Trade-offs

To be updated during implementation.

## Prerequisites

- `docs/aide/progress.md` debe ser actualizado a 📋 al iniciar.
- Al finalizar, actualizar `docs/aide/progress.md` a ✅.
