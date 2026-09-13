# Item 031: Política de host keys configurable por servidor

## Description

Implementar la gestión de políticas de `host keys` en `src/odin/transfer.py` según la configuración de cada servidor: `strict` (comportamiento por defecto, falla si no se conoce), `known_hosts` (uso de archivo preexistente), `accept-new` (registra la clave si es nueva) e `insecure` (no verifica). Asegurar que la política sea aplicada correctamente por servidor.

## Acceptance Criteria

- [ ] Implementación de la lógica de políticas de host keys en `src/odin/transfer.py`.
- [ ] Soporte para política `strict`.
- [ ] Soporte para política `known_hosts`.
- [ ] Soporte para política `accept-new`.
- [ ] Soporte para política `insecure`.
- [ ] Implementación de tests unitarios para cada política.

## Implementation Steps

1. Definir el enum o tipo para las políticas de `host keys`.
2. Implementar la lógica de selección y aplicación del método de verificación de `paramiko` (ej. `AutoAddPolicy` para `accept-new` o `insecure`).
3. Implementar la lógica para cargar `known_hosts` si la política es `known_hosts`.
4. Asegurar que la política se lea de la configuración del servidor.
5. Implementar tests unitarios que validen el comportamiento de cada política.

## Testing Strategy

- Unit tests: Mock de `paramiko.SSHClient` para verificar qué política de `host keys` se aplica según la configuración:
    - `strict`: verificar que falla o lanza error si la clave no está en `known_hosts`.
    - `accept-new`: verificar que se usa `AutoAddPolicy`.
    - `insecure`: verificar que se usa `WarningPolicy` o similar.
    - `known_hosts`: verificar que intenta cargar el archivo de hosts.

## Dependencies

- `src/odin/transfer.py` (desarrollo en paralelo con Item 030).

## Decisions & Trade-soffs

To be updated during implementation.

## Prerequisites

- `docs/aide/progress.md` debe ser actualizado a 📋 al iniciar.
- Al finalizar, actualizar `docs/aide/progress.md` a ✅.
