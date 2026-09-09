# Queue 002 — Respaldo Firebird (Etapa 2 del roadmap)

> **Paso 4 del flujo AIDE.** Lote de ~10 work items priorizados desde `docs/aide/roadmap.md` y `docs/aide/progress.md`. Cubre la Etapa 2: generación de respaldos `.fbk` usando `gbak`, auto-detección de binarios y soporte multi-base. Dimensión total: ~1 semana.
>
> Para ejecutar un item: iniciar una nueva sesión de chat y correr `/speckit.aide.create-item` con la descripción del item.

### Item 010: Implementación core de `src/odin/backup.py` (Ejecución de `gbak`)
Implementar la lógica base para ejecutar `gbak -b` utilizando `subprocess`. La implementación debe capturar `stdout` y `stderr`, manejar timeouts configurables y detectar fallos tanto por exit code como por patrones de error conocidos en la salida de `gbint`.

### Item 011: Auto-detección de `gbak` por plataforma y override
Implementar la lógica para localizar automáticamente el binario `gbak` en rutas típicas de Linux (`/usr/bin`, `/opt/firebird/bin`) y Windows (`C:\Program Files\Firebird\...\bin`). Incluir la capacidad de sobreescribir esta ruta mediante la propiedad `gbak_path` en la configuración JSON.

### Item 012: Modelo de datos `BackupResult` y registro de errores
Crear la clase `BackupResult` (dataclass) para encapsular el estado del respaldo (éxito/fallo), la ruta del archivo `.fbk` generado, su tamaño, la duración y cualquier mensaje de error capturado. Asegurar que los errores de `gbak` se mapeen correctamente a este modelo.

### Item 013: Integración de `odin run` para la fase de respaldo
Implementar el subcomando `run` en `src/odin/cli.py` (o la lógica necesaria) para que, al detectar la configuración de la Etapa 2, ejecute el proceso de respaldo para todas las bases de datos listadas en el JSON. El proceso debe ser secuencial y reportar el progreso.

### Item 014: Validación post-respaldo y manejo de archivos
Implementar verificaciones automáticas tras la ejecución de `gbak`: comprobar que el archivo `.fbk` existe, que su tamaño es mayor a 0 y que es accesible. Manejar la creación del directorio `work_dir` si no existe previamente.

### Item 015: Soporte para múltiples bases de datos y nombrado dinámico
Extender la lógica de backup para iterar sobre todas las bases de datos definidas en la sección `databases` de la configuración. Implementar el esquema de nombres de salida `<nombre_bd>_<timestamp>.fbk` para evitar colisiones y permitir trazabilidad.

### Item 016: Configuración de parámetros de `gbak` (charset, user, password)
Añadir soporte para pasar parámetros adicionales de `gbak` (como `charset`, `role`, `user`, `password`) desde la configuración JSON hacia el comando de ejecución, asegurando que las credenciales se manejen de forma segura y no queden expuestas en logs.

### Item 017: Implementación de Tests de Integración (Mocking de Subprocess)
Crear tests en `tests/test_backup.py` utilizando `unittest.mock` para simular la ejecución de `subprocess.run`. Probar casos de éxito, errores de `gbak` (exit code != 0), timeouts y captación de mensajes de error en `stderr`.

### Item 018: Implementación de Tests de Integración (Firebird Real/Container)
(Opcional/Deseable) Crear un test de integración marcado con `@pytest.mark.integration` que utilice un entorno de Firebird real (o un contenedor Docker si disponible) para validar que el flujo `odin run` -> `gbak` -> `archivo .fbky` es funcional y produce archivos válidos.

### Item 019: Refactorización y limpieza de la Etapa 2
Revisar que toda la lógica de la Etapa 2 esté integrada correctamente en el pipeline, que los logs de la etapa de backup sean coherentes con el sistema de logging de la Etapa 1 y que la documentación de `odin run` se haya actualizado.

---

**Total: 10 items.** Al completar este lote, la Etapa 2 del roadmap quedará cerrada y la Etapa 3 (compresión 7z) podrá comenzar. El siguiente lote (`queue-003.md`) arrancará en el item 020.
