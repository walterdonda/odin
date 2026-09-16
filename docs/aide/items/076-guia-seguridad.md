# Item 076: Guía de seguridad `docs/security.md`

## Description

Escribir `docs/security.md`, la guía de seguridad de ODIN: el documento que
explica qué protege el producto, qué no, y cómo desplegarlo sin exponer
credenciales. ODIN guarda secretos (contraseñas de bases Firebird, SFTP y
SMTP, passphrases de claves privadas) en un **JSON legible** —una decisión
consciente de simplicidad operativa— y mitiga el riesgo con permisos del
archivo, enmascarado en logs/informes/estado y recomendaciones de
autenticación. La guía debe hacer explícito ese modelo.

Contenido requerido:

1. **Modelo de amenazas y decisión de credenciales en JSON legible**: qué
   activos hay (credenciales, contenido de claves, configuración, backups),
   quién puede atacarlos (usuario local sin privilegios, otro proceso del
   host, acceso físico/backup del host, logs compartidos), superficie de
   exposición y la justificación de no usar vault/KMS (fuera de alcance de la
   visión), con sus contrapartidas.
2. **Permisos del archivo de configuración**: `chmod 600` y dueño/grupo en
   Linux (`chown odin:odin`, directorio `750`), ejemplos `icacls` para
   Windows (retirar herencia y conceder solo al dueño/cuenta del servicio),
   ACL de la cuenta del servicio, exclusión de control de versiones
   (`.gitignore` ya cubre `*.log`; el JSON real **no se versiona**), y qué
   reporta `odin validate` (advertencia por acceso de grupo/otros; en Windows
   la verificación se omite con nota) enlazando a la guía.
3. **Autenticación SFTP por clave privada frente a password**:
   `ssh-keygen` (Ed25519/RSA), passphrase obligatoria y campo `passphrase`,
   campos `private_key`/`passphrase` del JSON, expansión de `~`, permisos de
   la clave (`600`), rechazo de PPK (formato PuTTY) y por qué la clave es
   preferible (el password viaja al servidor y queda en la config).
4. **Políticas de host key** (`servers[].host_key_policy`): `strict` (default)
   con `known_hosts` administrado, `accept-new` (primer contacto, registra la
   clave) e `insecure` (sin verificación: riesgo de MITM) — cuándo usar cada
   una y por qué `insecure` solo en redes controladas.
5. **Garantías de enmascarado y sus límites**: qué enmascara ODIN (logs con
   `MaskingFilter`, asunto/cuerpo del correo, `scheduler_state.json`,
   resumen de consola) y qué **no** puede (el argumento `-password` de `gbak`
   puede verse en la lista de procesos del SO mientras corre el respaldo:
   documentar la mitigación —usuario dedicado, `hidepid`, ventana breve—;
   el JSON es legible por diseño).
6. **TLS/SSL en SMTP**: `starttls: true` (default) vs `smtp.ssl: true` (SSL
   implícito) vs plano (`starttls: false`: solo relays locales), con la
   advertencia de `validate` para canal sin cifrar.
7. **Mínimo privilegio de la cuenta del servicio**: usuario dedicado sin
   login interactivo, acceso de lectura al JSON, escritura solo en
   `work_dir`/logs, ejecución de `gbak` y acceso de red a Firebird/SFTP/SMTP.
8. **Checklist de despliegue seguro y rotación de credenciales**: lista
   accionable (permisos, clave SSH, host key strict, TLS, cuenta del
   servicio, no versionar el JSON, verificar `odin validate --strict`) y
   procedimiento de rotación (bases, SFTP, SMTP, clave con passphrase) sin
   cortar el servicio (editar el JSON y `odin service reload`).

Además: enlazar la guía desde `README.md` (sección de seguridad, Item 075 del
mismo lote) y `docs/service.md` (cuenta del servicio/permisos), y ajustar los
mensajes de permisos de `validate` (`_check_config_file`, `_check_private_keys`)
para que apunten a `docs/security.md`, actualizando los tests si el texto
cambia. No se toca comportamiento: solo el texto de las advertencias.

## Acceptance Criteria

- [ ] `docs/security.md` existe con el modelo de amenazas y la decisión
      explícita de credenciales en JSON legible (incluida su justificación y
      contrapartidas).
- [ ] Sección de permisos con `chmod 600`/dueño/grupo, ejemplos `icacls` de
      Windows, ACL de la cuenta del servicio, exclusión de control de
      versiones y el comportamiento real de `odin validate`.
- [ ] Sección de autenticación SFTP por clave (`ssh-keygen`, passphrase,
      `private_key`/`passphrase`, `~`, permisos `600`, rechazo de PPK) frente
      a password.
- [ ] Sección de host keys con las cuatro políticas y sus riesgos.
- [ ] Garantías de enmascarado (logs, informes, `scheduler_state.json`) y
      límites documentados (al menos `-password` de `gbak` en la lista de
      procesos y su mitigación).
- [ ] SMTP con TLS/SSL y mínimo privilegio de la cuenta del servicio.
- [ ] Checklist de despliegue seguro y procedimiento de rotación de
      credenciales.
- [ ] Enlaces reales desde `README.md` y `docs/service.md` a
      `docs/security.md`.
- [ ] Los mensajes de permisos de `validate` apuntan a `docs/security.md`
      (config y clave privada), con los tests correspondientes en verde.
- [ ] Gates en verde: `uv run pytest tests/test_validate.py -q`,
      `uv run pytest`, `uv run ruff check src/odin tests`,
      `uv run mypy src/odin`.
- [ ] Evidencia registrada en "Decisions & Trade-offs".

## Implementation Steps

1. Relevar el comportamiento real a documentar: mensajes de permisos de
   `src/odin/validate.py` (config y clave privada), campos de `ServerConfig`
   (`host_key_policy`, `auth.method`, `private_key`, `passphrase`), manejo de
   TLS de `notify.py`, enmascarado de `log.py`/`scheduler.py` y la
   documentación de riesgos ya presente en `examples/README.md`/`docs/service.md`.
2. Escribir `docs/security.md` con las ocho secciones del Description, con
   ejemplos de comandos reales (`chmod`, `chown`, `icacls`, `ssh-keygen`).
3. Enlazar desde `README.md` (sección Seguridad) y `docs/service.md` (puntos
   de permisos de la cuenta/cuenta del servicio).
4. Ajustar los mensajes de permisos de `validate.py` para que citen
   `docs/security.md`; actualizar `tests/test_validate.py` si el texto
   cambia (hoy no se fija el texto de recomendación, pero sí severidades).
5. Correr los gates y actualizar `docs/aide/progress.md` (📋 → 🚧 → ✅) y este
   spec con decisiones/evidencia.

## Testing Strategy

- `uv run pytest tests/test_validate.py -q` → mensajes de permisos (config
  `600`/`644`, clave privada, host Windows) sin regresiones de severidad.
- `uv run pytest -q` → suite completa.
- `uv run ruff check src/odin tests` y `uv run mypy src/odin` → gates.
- Verificación manual de enlaces: `docs/security.md` existe desde
  `README.md` y `docs/service.md` (grep de la ruta relativa).
- Contraste de afirmaciones con el código: las políticas de host key, los
  campos del JSON, el timeout SMTP y el enmascarado se verifican contra
  `src/odin/transfer.py`, `src/odin/notify.py`, `src/odin/log.py` y
  `src/odin/scheduler.py` (no documentar comportamiento inexistente).

## Dependencies

- Item 075 (mismo lote): la sección de seguridad del README enlaza esta guía.
- `docs/service.md` (Items 067/074) y `examples/README.md` (Item 007):
  contenido de permisos/cuenta ya documentado que esta guía referencia.
- `src/odin/validate.py` (textos de permisos) y `tests/test_validate.py`.
- `src/odin/log.py` (enmascarado), `src/odin/notify.py` (TLS), 
  `src/odin/transfer.py` (host keys/auth) como fuentes de verdad.

## Decisions & Trade-offs

- **Precisión contra el código, no seguridad genérica**: cada afirmación se
  contrastó con la implementación. Hallazgos relevantes documentados tal cual:
  - ODIN carga la clave SFTP con `paramiko.RSAKey.from_private_key_file`
    (`transfer.py:198`), así que la guía recomienda **RSA 4096**
    (`ssh-keygen -t rsa -b 4096`) y declara explícitamente que Ed25519 todavía
    no está soportado (no se documentó lo que el código no hace).
  - `smtplib` usa `ssl._create_stdlib_context()` cuando no se le pasa contexto
    (`SMTP.starttls`/`SMTP_SSL.__init__` de Python 3.14): el canal **se cifra
    pero el certificado no se verifica**. Se documentó como limitación en §6
    (corregirlo cambia comportamiento y queda fuera del alcance del item).
  - `known_hosts` llama `load_system_host_keys()` y deja el `RejectPolicy`
    por defecto (equivalente explícito de `strict`); `insecure` es
    `WarningPolicy`. La tabla de políticas refleja esa semántica real.
  - Límites del enmascarado: los campos de `iter_secret_fields()` (bases,
    compresión, SFTP, SMTP), PEM por patrón, correo/consola/estado
    enmascarados; se documentó el `-password` de `gbak` visible en la lista de
    procesos y sus mitigaciones (cuenta dedicada, `hidepid=2`), más el umask
    por defecto del `odin.log` y los `.fbk` como activo de datos.
- **Permisos del JSON**: se dieron ejemplos reales de `chmod`/`chown`
  (`600`, directorio `750`) e `icacls` con `/inheritance:r` y `:(R)` para la
  cuenta del servicio, advirtiendo que los nombres de grupos integrados se
  localizan por idioma (los SIDs siempre funcionan).
- **Mensajes de `validate`**: se agregó un constante `_SECURITY_GUIDE =
  "docs/security.md"` y los tres mensajes de permisos (modo del JSON,
  omisión de ACL en Windows y permisos de la clave privada) ahora citan la
  guía. Fue un cambio de **texto** (ninguna severidad ni check cambió), con
  los tests de `test_validate.py` extendidos para afirmar el puntero.
- **Enlaces**: `README.md` (sección Seguridad) y `docs/service.md` (§1.3
  cuenta, §3.2 usuario dedicado, §4.2 cuenta Windows) enlazan la guía; de
  paso se corrigió un ancla preexistente rota en `docs/service.md`
  (`#logging` → `#6-logging`, verificado con un chequeo de anclas).
- **Checklist y rotación**: la rotación se apoya en la recarga en caliente
  (`odin service reload`) ya documentada, sin inventar comandos nuevos.

**Evidencia:** `test -f docs/security.md` → existe; chequeo programático de
enlaces relativos y anclas en `README.md`, `docs/security.md`,
`docs/service.md` y `docs/firebird.md` → 0 rotos; `uv run odin validate
--config examples/config.linux.json` (y el de Windows) muestra la advertencia
de permisos con "guía de seguridad: docs/security.md";
`uv run pytest tests/test_validate.py -q` → **54 passed**; suite completa
`uv run pytest -q` → **652 passed + 8 skipped in 71.12 s**;
`uv run ruff check src/odin tests` → All checks passed;
`uv run mypy src/odin` → Success 19 files.

## Prerequisites

- **Servicios requeridos**: ninguno (documentación + textos de mensajes);
  `uv` en el `PATH` para los gates.
- **Configuración de entorno**: ninguna.
- **Checklist de validación manual**:
  - [ ] `test -f docs/security.md` y `grep -c "security.md" README.md
        docs/service.md` ≥ 1 en cada uno.
  - [ ] `uv run odin validate --config examples/config.linux.json` → la
        advertencia de permisos (si aplica) cita la guía.
  - [ ] `uv run pytest tests/test_validate.py -q` verde.
  - [ ] Los ejemplos de `icacls`/`ssh-keygen` son comandos reales (sintaxis
        verificada contra la doc oficial).
- **Resultados esperados**: guía completa, enlazada desde README y
  `docs/service.md`; mensajes de `validate` que apuntan a la guía.
- `docs/aide/progress.md` debe reflejar el avance (📋 → 🚧 → ✅) al completar.
- Al finalizar, actualizar `docs/aide/progress.md` con la evidencia del item
  (este item cierra parte del entregable "Guía de seguridad" de la Etapa 8;
  la etapa completa no se marca hasta los Items 077/078).
