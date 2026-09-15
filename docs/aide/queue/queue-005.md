# Queue 005 — Notificación por correo, flujo one-shot y retención local (Etapa 5 del roadmap)

> **Paso 4 del flujo AIDE.** Lote de 10 work items priorizados desde `docs/aide/roadmap.md` y `docs/aide/progress.md`. Cubre la Etapa 5: envío del informe de ejecución por correo (siempre, éxito o fallo), cierre del ciclo end-to-end de `odin run`, exit codes finales y retención local (F8). Dimensión total: ~1 semana.
>
> **Agrupación de implementación:** los items se ejecutan en 4 lotes por afinidad de contexto (misma superficie de archivos). Cada lote se ejecuta en una sesión con `/speckit.aide.execute-batch <items>` (ver el comando exacto en cada lote), que crea los specs faltantes, implementa item por item y actualiza el progreso. La numeración de items no cambia.
>
> **Estado de partida:** la Etapa 4 quedó cerrada (`odin run` = respaldo → compresión → transferencia, suite 327 passed + 1 skipped). `src/odin/notify.py` y `src/odin/retention.py` no existen todavía; `src/odin/pipeline.py` devuelve `PipelineResult(backup, transfers)` sin fase de correo. `NotificationConfig` (`to`, `from_`, `smtp`, `log_tail_lines=50`) y `LocalConfig.retention_days` ya se parsean desde la Etapa 1. El smoke test multiplataforma (Item 009) sigue pendiente y queda delegado a la Etapa 8 por no ser verificable localmente.

---

## Lote A — Núcleo de notificación (`src/odin/notify.py`)

> Items 039, 040, 041 y 042. Cliente SMTP, render del informe, captura de la cola de log y tests unitarios con mock de `smtplib`. Todos giran alrededor del mismo módulo y su superficie de tests.
>
> **Comando:** `/speckit.aide.execute-batch 039-042`

### Item 039: Implementación core de `src/odin/notify.py` (cliente SMTP con STARTTLS/SSL)
Implementar el cliente SMTP sobre `smtplib` que envía el informe a `notification.to` desde `notification.from_` usando `notification.smtp` (`host`, `port`, `starttls`, `username`, `password`). Comportamiento de transporte: STARTTLS cuando `starttls: true` (default); SMTP plano cuando `starttls: false` (relays locales); y SSL implícito (puerto 465) mediante el campo opcional `smtp.ssl` (default `false`, mutuamente excluyente con `starttls: true` y validado en `config.py`), agregado a `_SMTP_FIELDS`, a los ejemplos y documentado. Timeouts de conexión/operación parametrizables con defaults sensatos (p. ej. 30 s) inline en `notify.py` (sin extender el JSON por ahora). Definir `NotificationResult` (frozen dataclass: `success`, `duration_seconds`, `error_message`, destinatario) y `EmailNotifier` con `from_config(config)`; los errores operativos esperados (`SMTPException`, `OSError`, `socket.timeout`) **no** se propagan: se reportan en el resultado y se loguean sin exponer credenciales. El módulo expone `__all__` y docstring.

### Item 040: Render del informe de ejecución (asunto y cuerpo en texto plano)
Implementar en `src/odin/notify.py` una función pura (sin SMTP) que construya el mensaje desde `PipelineResult` + `Config`: asunto con estado global y hostname (p. ej. `[ODIN] FALLO PARCIAL — respaldo de <hostname> (<fecha>)`) y cuerpo texto plano con: estado global derivado del `BatchBackupResult` final (ÉXITO si todas las bases completaron las tres fases; PARCIAL si hubo mezcla; FALLO si falló todo o `error_message` de lote / lote vacío); por base, respaldo (ruta, tamaño, duración) y compresión (tamaño comprimido, duración) y el error de la fase que falló (`error_message`, `compression_error_message`, `transfer_error_message`); por servidor destino, `database → server: OK/FALLO` con motivo y bytes/duración; totales de duración y contadores. Cubrir los casos borde: sin servidores configurados, base sin transferencia, lote con `error_message`. Determinista y testeable sin red. El texto final debe pasar por `SecretMasker.from_config(config)` como segunda barrera (patrón del Item 038): el correo **nunca** incluye credenciales ni el backup adjunto.

### Item 041: Cola de log del informe (`notification.log_tail_lines`) y enmascarado del correo
Implementar en `src/odin/log.py` un `TailBufferHandler` (subclase de `logging.Handler` con `collections.deque(maxlen=N)`) que capture las últimas `notification.log_tail_lines` líneas ya formateadas y enmascaradas por el `MaskingFilter` existente, y los helpers para adjuntarlo/removerlo del logger `odin` (context manager recomendado). `log_tail_lines == 0` desactiva la cola. Integrar el buffer en la fase de notificación del pipeline (Item 043): las líneas capturadas durante la ejecución se pasan al render del Item 040 y aparecen al final del cuerpo del correo bajo un encabezado "Últimas líneas del log". Garantizar doble barrera de enmascarado (handler del log + `SecretMasker` sobre el mensaje final). Tests de que el buffer respeta `maxlen`, no retiene texto previo al attach y no filtra secretos.

### Item 042: Tests unitarios de notificación con mock de `smtplib`
Suite `tests/test_notify.py` con `unittest.mock` de `smtplib.SMTP`/`smtplib.SMTP_SSL` y de `socket`: STARTTLS invocado solo cuando corresponde; login con usuario/contraseña; modo plano y modo SSL; envelope correcto (`from`/`to`); timeouts propagados como fallo en `NotificationResult` sin excepción; `SMTPAuthenticationError`, `SMTPConnectError` y `ConnectionRefusedError` → resultado fallido con mensaje claro; `sendmail`/`send_message` fallido → resultado fallido; éxito → `success=True` con duración. Tests del render (Item 040): contenido por estado ÉXITO/PARCIAL/FALLO, cifras por base y servidor, caso sin servidores y lote fallido. Test de ausencia de secretos (contraseñas de BD/SFTP/SMTP y rutas de claves) en asunto y cuerpo, y de inclusión de la cola de log cuando está configurada. Tests de parseo en `tests/test_config.py` para `smtp.ssl` (mutuamente excluyente con `starttls`).

---

## Lote B — Integración one-shot y exit codes (`src/odin/pipeline.py`, `src/odin/cli.py`)

> Items 043 y 044. El correo entra al pipeline que ya usan `odin run` (y reutilizará el scheduler de la Etapa 6); después se cierra la matriz de exit codes y el resumen de consola. Un solo pase sobre `pipeline.py`/`cli.py`.
>
> **Comando:** `/speckit.aide.execute-batch 043,044`

### Item 043: Integración del correo en `odin run` (siempre, SMTP caído no crashea)
Agregar la fase de notificación a `run_pipeline` (`src/odin/pipeline.py`): al final de las tres fases y con el agregado ya construido, enviar el informe con un `notifier` inyectable (default `EmailNotifier.from_config(config)`); `PipelineResult` gana `notification: NotificationResult | None`. El correo se envía **siempre**, incluidos lote fallido por `error_message`, lote vacío y fallo total; el buffer del Item 041 se adjunta durante la ejecución y se pasa al render. Si SMTP falla: no hay crash ni excepción, el error queda en el log y en `NotificationResult.error_message`, y el exit code no puede ser 0 (una corrida sin correo incumple C2/C4): degradar 0 → 1 (error interno de la fase de notificación), documentando la decisión en docstring y README. Ajustar `_install_fake_executor` de `tests/test_cli.py` para parchear `odin.pipeline.EmailNotifier` y que los tests existentes no intenten SMTP real. Tests de pipeline con notifier doble: invocado exactamente una vez por corrida con el mensaje renderizado, también en fallo total; notifier que falla no interrumpe el retorno del pipeline.

### Item 044: Exit codes finales y resumen de consola consistentes con el correo
Cerrar la matriz completa de exit codes de `odin run` con la notificación incluida y documentarla: `0` todas las bases completaron las tres fases **y** correo enviado; `3` mezcla de éxitos y fallos (cualquier fase); `4` fallo total / respaldo no ejecutado / lote vacío; `2` error de configuración; `1` error interno o fallo de notificación en una corrida por lo demás exitosa. Extender `_print_backup_summary` (o el resumen de `_cmd_run`) con una línea del resultado de la notificación ("Correo enviado a X" o "Correo NO enviado: motivo") enmascarada; actualizar el help/description de `run` y del parser (`cli.py:83-141`) para mencionar el correo. Tests de CLI: los cinco códigos, incluido el caso pipeline OK + SMTP caído → 1, y ausencia de secretos en la línea impresa. Actualizar la tabla de exit codes del README.

---

## Lote C — Retención local (`src/odin/retention.py`, F8)

> Items 045 y 046. Módulo nuevo de política de limpieza y su integración en el flujo (después del correo, según el flujo de la visión), más el cierre del mensaje de `validate.py` que hoy anuncia la retención como "Etapa 5" futura.
>
> **Comando:** `/speckit.aide.execute-batch 045,046`

### Item 045: Implementación core de la retención local (`src/odin/retention.py`)
Implementar la limpieza opcional de respaldos locales (F8) según `local.retention_days`: eliminar `.fbk` y `.fbk.7z` de `work_dir` con antigüedad mayor a N días (por `mtime`), **solo** archivos gestionados por ODIN — nombre que cumpla la convención `<nombre_bd>_<timestamp>.fbk` / `<nombre_bd>_<timestamp>.fbk.7z` de las Etapas 2-3. `retention_days == 0` = deshabilitado. Seguridad: el path resuelto debe quedar dentro de `work_dir` (sin `..`), no seguir symlinks, solo archivos regulares, nunca tocar el directorio ni archivos ajenos (`config.json`, `odin.log`, etc.), y jamás los artefactos recién creados por la corrida actual (defensa extra: `mtime >=` inicio de la corrida queda excluido). Definir `RetentionResult` (examinados, eliminados, bytes liberados, errores por archivo, duración) y un ejecutor con aislamiento de fallos: un borrado fallido (p. ej. `PermissionError`/`OSError`) se registra y no interrumpe el resto. Idempotente. Tests unitarios con `tmp_path`: frontera exacta del cutoff, archivos ajenos intactos, subdirectorios/ symlinks ignorados, `retention_days=0` no-op, error de borrado aislado.

### Item 046: Integración de la retención en el pipeline, reporte y actualización de `validate`
Insertar la fase de retención en `run_pipeline` **después del envío del correo** (orden del flujo de la visión: recopilación → correo → limpieza → exit code), con el ejecutor inyectable; `PipelineResult` gana `retention: RetentionResult | None`. La retención no aparece en el correo (se envía antes) pero sí en el log y en el resumen de consola: línea "Retención local: N archivo(s) eliminado(s), X MB liberados" enmascarada. Política de fallo: la retención es función secundaria; sus errores se reportan y loguean pero **no** alteran el exit code (decisión documentada). Actualizar `validate.py:610-624` para describir el comportamiento real (sin "(Etapa 5)") y revisar que la advertencia de `retention_days=0` siga siendo coherente. Tests: pipeline con retención doble verifica el orden respecto de la notificación y el aislamiento; CLI imprime el resumen de retención; tests de `validate` actualizados.

---

## Lote D — Verificación y cierre de Etapa 5

> Items 047 y 048. Test de integración con un servidor SMTP efímero in-process (mismo enfoque que el sshd ephemeral del Item 037, sin dependencias externas) y documentación/cierre con los gates de calidad.
>
> **Comando:** `/speckit.aide.execute-batch 047,048`

### Item 047: Test de integración con servidor SMTP efímero in-process
Crear `tests/test_notify_integration.py` (marcado `@pytest.mark.integration`, skip seguro) con un servidor SMTP mínimo in-process sobre loopback y puerto efímero implementado con stdlib (`socketserver` o `asyncio`): saludo, `EHLO`, `AUTH LOGIN` opcional, `MAIL FROM`/`RCPT TO`/`DATA`, captura del mensaje. Casos: `odin run` con dobles de respaldo/compresión/transferencia y notificación real → el servidor recibe el destinatario de `notification.to` y un cuerpo con el resumen esperado (estado, bases, servidores); fallo de conexión contra puerto cerrado → exit code ≠ 0, sin crash, con entrada en el log; ausencia de secretos en el mensaje recibido. Variante opcional: reutilizar el Firebird de prueba por Docker del Item 018 (skip si no está disponible) para la demostración punta a punta `gbak + 7z + correo` contra el catcher local. Es el sustituto local de "correo recibido en la casilla de control" del criterio de aceptación.

### Item 048: Documentación y cierre de la Etapa 5
Actualizar `README.md`: sección "Notificación por correo" (config SMTP, STARTTLS/SSL, `log_tail_lines`, contenido del informe, nunca adjunta el backup, nunca secretos, qué pasa si SMTP cae y su efecto en el exit code) y sección "Retención local" (`retention_days`, qué archivos se borran, política de fallo); ajustar la descripción de `odin run` y los ejemplos si se agregó `smtp.ssl`. Revisar coherencia de docstrings módulo a módulo (`cli.py:83-141` describe las etapas acumuladas; `log.py:21` anuncia el enmascarado "para los correos de la Etapa 5" ya implementado). Verificación explícita de los criterios de aceptación de la Etapa 5 del roadmap con evidencia (tests/ salidas), y gates de calidad: `uv run pytest`, `uv run ruff check src/odin tests`, `uv run mypy src/odin` en verde. Actualizar `docs/aide/progress.md` (Etapa 5 ✅ si los criterios quedan verificados) y `docs/service.md` no aplica aún (Etapa 7).

---

**Total: 10 items en 4 lotes.** Al completar este lote, la `odin run` quedará cerrada end-to-end (respaldo → compresión → transferencia → correo → retención, con exit codes finales) y la Etapa 6 (scheduler interno) podrá comenzar. El siguiente lote (`queue-006.md`) arrancará en el item 049.
