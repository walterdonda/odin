# Changelog

Todos los cambios relevantes de ODIN se documentan en este archivo.

El formato se basa en [Keep a Changelog](https://keepachangelog.com/es/1.1.0/)
y el proyecto adhiere a [Versionado Semántico](https://semver.org/lang/es/).

## Unreleased

## 1.0.0 - 2026-09-16

Primera release estable: respaldo externo de bases Firebird 2.5 → 6 con
`gbak`, compresión 7z, transferencia SFTP y notificación por correo, operable
como servicio residente en Windows Server y Linux LTS.

### Añadido

- **F1. Respaldo Firebird 2.5 → 6 (`gbak`)**: ejecución con timeout, charset,
  rol y credenciales por base, auto-detección de `gbak` con override
  `gbak_path` y validación del `.fbk` generado; matriz de compatibilidad
  verificada con Firebird 2.5.9, 3.0.9, 4.0.5, 5.0.4 y 6.0-snapshot
  (`docs/firebird.md`).
- **F2. Compresión 7z**: `.fbk` → `.fbk.7z` con `py7zr`, nivel configurable
  (0 = sin compresión, 1–9 LZMA2), escritura atómica y cifrado AES-256
  opcional con `compression.password`.
- **F3. Configuración JSON legible y OS-agnóstica**: único archivo con bases,
  servidores SFTP, SMTP, compresión, retención y scheduler; rutas con `/` o
  `\`, `~` y relativas al propio JSON; validación completa con `odin validate`
  (estructura, rutas, permisos, conectividad básica y `--strict`).
- **F4. Transferencia SFTP con paramiko**: autenticación por contraseña o
  clave privada (passphrase, `~`, rechazo de PPK), políticas de host key
  (`strict` por defecto, `known_hosts`, `accept-new`, `insecure`), creación de
  directorios remotos, verificación de tamaño, reintentos con backoff y
  aislamiento de fallos por servidor.
- **F5. Notificación por correo**: informe por ejecución (ÉXITO/PARCIAL/FALLO,
  detalle por base y servidor, totales y cola de log) enviado **siempre** por
  SMTP con STARTTLS (default) o SSL implícito, sin credenciales ni adjuntos.
- **F6. CLI y operación**: `odin validate`, `odin run` one-shot y
  `odin service run|status|reload|install|uninstall|start|stop`, con exit
  codes diferenciados (0 éxito, 3 parcial, 4 fallo, 2 configuración, 1
  interno), logging con rotación (5 MiB × 5) y opción `--config`/
  `ODIN_CONFIG`.
- **F7. Scheduler propio y modo servicio**: jobs cron por subconjunto de
  bases con timezone global, políticas `skip_if_running` y `on_misfire`,
  recarga en caliente (`SIGUSR1` / archivo de control / `odin service
  reload`), Windows Service con arranque automático y política de reinicio, y
  unit systemd de referencia con `Restart=always` (`deploy/odin.service`).
- **F8. Retención local**: limpieza de `.fbk`/`.fbk.7z` gestionados por ODIN
  según `local.retention_days`, con frontera estricta y protección de los
  archivos de la corrida en curso.
- **Distribución e instalación**: `uv tool install` (wheel, repositorio o
  `uvx`), gate único `scripts/verify.py` en Linux y Windows, CI
  multiplataforma lista para habilitar (`linux`/`windows`) y documentación
  final: `README.md`, `docs/firebird.md`, `docs/security.md` y
  `docs/service.md`.
- **Calidad**: suite de tests (unitarios, end-to-end con dobles, integración
  con contenedores Firebird, sshd ephemeral in-process y catcher SMTP) más
  `ruff` y `mypy` estrictos.

### Seguridad

- Enmascarado de secretos en logs, informes de correo, resumen de consola y
  `scheduler_state.json`; el JSON de configuración contiene credenciales en
  texto legible por decisión explícita, con guía de permisos (`chmod
  600`/`icacls`), claves SSH con passphrase y checklist de rotación en
  `docs/security.md`.

### Plataformas

- Windows Server 2016+ (incluye Windows Service nativo con `pywin32`) y Linux
  LTS (Ubuntu/Debian/RHEL/Rocky/AlmaLinux) con Python ≥ 3.14 gestionado por
  `uv`.
