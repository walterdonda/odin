# Item 034: Aislamiento de fallos por servidor y `TransferResult`

## Description

Implementar un ejecutor de transferencias que recorra la lista de servidores destino, aislando los fallos: si un servidor falla tras agotar reintentos, se registra el error y se continúa con el siguiente. Definir el dataclass `TransferResult` para reportar el estado (éxito/fallo), tamaño transferido, duración y mensaje de error por servidor.

## Acceptance Criteria

- [ ] Implementación de un ejecutor de transferencias en `src/odin/transfer.py`.
- [ ] El ejecutor debe iterar sobre todos los servidores configurados sin detenerse ante fallos individuales.
- [ ] Definición del dataclass `TransferResult` con los campos: estado, tamaño transferido, duración y mensaje de error.
- [ ] Implementación de tests unitarios para el ejecutor y el dataclass.

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

To be updated during implementation.

## Prerequisites

- `docs/aide/progress.md` debe ser actualizado a 📋 al iniciar.
- Al finalizar, actualizar `docs/aide/progress.md` a ✅.
