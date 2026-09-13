# Item 033: Reintentos configurables y manejo de timeouts

## Description

Implementar una política de reintentos con backoff configurable por servidor ante errores de red transitorios o timeouts de conexión/operación. Los errores no deben abortar el proceso completo si hay otros servidores en la cola; cada servidor debe tener su propio manejo de errores y reintentos.

## Acceptance Criteria

- [ ] Implementación de lógica de reintentos en `src/odin/transfer.py`.
- [ ] Soporte para número de reintentos configurable por servidor.
- [ ] Soporte para backoff (espera entre reintentos) configurable.
- [ ] Uso de timeouts en las operaciones de `paramiko`.
- [ ] Aislamiento de fallos: un fallo en un servidor no interrumpe la cola de otros servidores.
- [ ] Implementación de tests unitarios.

## Implementation Steps

1. Definir la estructura de datos para la configuración de reintentos y timeouts en el modelo de configuración (si no existe o necesita extensión).
2. Implementar la lógica de reintento (bucle con delay/backoff) en el ejecutor de transferencias en `src/odin/transfer.py`.
3. Configurar los timeouts de `paramiko` (conexión y operación) usando los valores de la configuración.
4. Asegurar que los errores catastróficos (ej. error de autenticación) no desencadenen reintentos inútiles, mientras que errores de red sí lo hagan.
5. Implementar tests unitarios simulando fallos de red y verificando el número de reintentos y los tiempos de espera.

## Testing Strategy

- Unit tests: Mock de `paramiko.SSHClient.connect` y `paramiko.SFTPClient.put`:
    - Caso de éxito tras un fallo temporal (verificar número de reintentos).
    - Caso de fallo tras agotar todos los reinstancias (verificar error reportado).
    - Caso de error de autenticación (verificar que NO reintente y falle de inmediato).
    - Verificar que el backoff/delay se aplica correctamente.

## Dependencies

- `src/odin/transfer.py`

## Decisions & Trade-offs

To be updated during implementation.

## Prerequisites

- `docs/aide/progress.md` debe ser actualizado a 📋 al iniciar.
- Al finalizar, actualizar `docs/aide/progress.md` a ✅.
