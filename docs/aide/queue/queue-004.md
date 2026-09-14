# Queue 004 — Transferencia SFTP con paramiko (Etapa 4 del roadmap)

> **Paso 4 del flujo AIDE.** Lote de ~9 work items priorizados desde `docs/aide/roadmap.md` y `docs/aide/progress.md`. Cubre la Etapa 4: envío de `.fbk.7z` a servidores destino vía SFTP con paramiko, con autenticación, verificación y reintentos. Dimensión total: ~1 semana.
>
> **Agrupación de implementación:** los items se ejecutan en 2 lotes por afinidad de contexto (mismo módulo/archivo). Cada lote se ejecuta en una sesión con `/speckit.aide.execute-batch <items>` (ver el comando exacto en cada lote).

---

## Lote A — Núcleo de transferencia (`src/odin/transfer.py`)

> Items 030, 031, 032, 033 y 034. Implementación de la lógica de conexión, políticas de seguridad, creación de directorios y reintentos.
>
> **Comando:** `/speckit.aide.execute-batch 030-034`

### Item 030: Conexión paramiko con autenticación por password y clave privada
Implementar la lógica base de conexión SSH/SFTP utilizando `paramiko`. Soporte para autenticación mediante contraseña (`password`) y clave privada (`key`), permitiendo el uso de rutas con `~` y manejo de `passphrase` opcional. El módulo debe reportar errores de conexión o de autenticación de forma clara sin exponer credenciales.

### Item 031: Política de host keys configurable por servidor
Implementar la gestión de políticas de `host keys` en `src/odin/transfer.py` según la configuración de cada servidor: `strict` (comportamente por defecto, falla si no se conoce), `known_hosts` (uso de archivo preexistente), `accept-new` (registra la clave si es nueva) e `insecure` (no verifica). Asegurar que la política sea aplicada correctamente por servidor.

### Item 032: Creación recursiva de directorios remotos y upload con verificación
Añadir la funcionalidad de crear directorios de forma recursiva en el servidor remoto si no existen antes de iniciar la transferencia. Tras el upload de cada `.fbk.7z`, realizar una verificación post-transferencia comparando el tamaño del archivo local contra el `stat` remoto para garantizar la integridad.

### Item 033: Reintentos configurables y manejo de timeouts (✅ Completado)
Implementar una política de reintentos con backoff configurable por servidor ante errores de red transitorios o timeouts de conexión/operación. Los errores no deben abortar el proceso completo si hay otros servidores en la cola; cada servidor debe tener su propio manejo de errores y reintentos.

### Item 034: Aislamiento de fallos por servidor y `TransferResult`
Implementar un ejecutor de transferencias que recorra la lista de servidores destino, aislando los fallos: si un servidor falla tras agotar reintentos, se registra el error y se continúa con el siguiente. Definir el dataclass `TransferResult` para reportar el estado (éxito/fallo), tamaño transferido, duración y mensaje de error por servidor.

---

## Lote B — Orquestación y cierre de Etapa 4 (`odin run` e integración)

> Items 035, 036, 037 y 038. Integración en el pipeline, actualización de reportes, tests y seguridad.
>
> **Comando:** `/speckit.aide.execute-batch 035-038`

### Item 035: Extensión del pipeline `odin run`: respaldo → compresión → transferencia (✅ Completado)
Integrar la fase de transferencia en el orquestador `src/odin/pipeline.py`. El flujo debe ser: ejecutar respaldo (Etapa 2), comprimir (Etapa 3) y, si exitosos, transferir a todos los servidores configurados (Etapa 4). El éxito de la ejecución global dependerá de la culminación exitosa de todas las fases para cada base de datos.

### Item 036: Integración de notificaciones y reporte de transferencia en el resumen (✅ Completado)
Actualizar el resumen de `odin run` y el logger para incluir información detallada sobre la fase de transferencia: rutas de archivos transferidos, tamaño, duración y estado por servidor destino. Asegurar que el `BatchTransferResult` se integre en el informe final que llegará por correo en la Etapa 5.

### Item 037: Tests de integración y unitarios para la transferencia SFTP (✅ Completado)
Implementar una suite de tests que incluya mocks de `paramiko.SSHClient` y `paramiki.SFTPClient` para cubrir casos de éxito, fallo de autenticación, error de red (reintentos) y verificación de tamaño fallida. Incluir tests de integración opcionales contra un servidor `sshd` local o contenedor para validar el flujo real.

### Item 038: Verificación de seguridad y enmascarado en la transferencia (✅ Completado)
Asegurar que ningún elemento de la configuración de los servidores (contrase<0xC2>ñas, rutas de claves privadas, passthrough de passphrase) aparezca en los logs de transferencia o en el reporte de salida. Validar que el enmascarado de secretos de la Etapa 1 se aplique correctamente a los nuevos campos de configuración de servidores de la Etapa 4.

---

**Total: 9 items en 2 lotes.** Al completar este lote, la Etapa 4 del roadmap quedará cerrada y la Etapa 5 (Notificación) podrá comenzar. El siguiente lote (`queue-005.md`) arrancará en el item 039.
