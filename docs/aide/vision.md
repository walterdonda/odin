# Visión del Proyecto — ODIN

> **Paso 1 del flujo AI-Driven Engineering (AIDE).** Este documento es la base de la que derivan el roadmap, el seguimiento de progreso, los work items y la implementación.

---

## 1. Resumen del Proyecto

**ODIN** es una herramienta de línea de comandos (CLI) escrita en Python que automatiza la estrategia de respaldo externo de bases de datos **Firebird (versiones 2.5 hasta 6)**:

1. Genera el respaldo lógico de la base de datos mediante la utilidad oficial de Firebird `gbak` (archivo `.fbk`).
2. Comprime el respaldo con **7z**.
3. Transfiere el archivo comprimido por **SSH/SFTP** a una lista de servidores remotos, cuya definición y credenciales residen en un archivo **JSON legible**.
4. Al finalizar (con éxito o con error), envía un **correo electrónico** a la casilla de control definida en la misma estructura JSON.
5. Se programa a sí mismo mediante un **scheduler propio** que le permite correr como **servicio residente** (Windows Service / daemon Linux), sin depender de cron ni de tareas programadas del sistema operativo.

El proyecto se instala y ejecuta con **uv**, tanto en **Windows Server** como en distribuciones **Linux LTS**.

### ¿Por qué existe este proyecto?

Las organizaciones que utilizan Vikingo suelen carecer de una estrategia de respaldo externa, automatizada y verificable. ODIN cubre ese hueco con una solución simple, auditable y sin infraestructura adicional: un único proceso que produce copias comprimidas, geo-distribuidas y notificaciones configurables (admins, gerencia).

---

## 2. Objetivos y Metas

| # | Objetivo | Resultado medible |
|---|----------|-------------------|
| G1 | Respaldo confiable de bases Firebird | Ejecución exitosa de `gbak` con `.fbk` íntegro y verificable para Firebird 2.5, 3.0, 4.0, 5.0 y 6.x |
| G2 | Reducción de tamaño y tiempo de transferencia | Archivo `.fbk` comprimido con 7z (nivel de compresión configurable) |
| G3 | Distribución externa de las copias | Transferencia SFTP exitosa a todos los servidores definidos en el JSON, con reintentos |
| G4 | Trazabilidad y verificación | Correo a la casilla de control en cada ejecución (éxito y fallo) con resumen de la operación |
| G5 | Instalación uniforme multiplataforma | Instalación idéntica vía `uv` en Windows Server y Linux LTS |
| G6 | Operación desatendida como servicio | Servicio residente con scheduler propio que ejecuta los respaldos según horario configurado, con logging persistente y monitoreo, en ambas plataformas |
| G7 | Compatibilidad con ejecución puntual | El modo one-shot (`odin run`) sigue disponible para respaldos manuales o integración con planificadores externos si se deseara |

---

## 3. Usuarios Objetivo

- **Administradores de sistemas / DBAs** de PyMEs y estudios de software con sistemas de gestión sobre Firebird, responsables de la política de backups.
- **Equipos de operaciones/DevOps** que necesitan una herramienta simple, scripteable y auditable, sin montar infraestructura ajena a la actual.
- **Modalidad de uso:** configuración única del JSON de autenticación/destinos y horarios; ODIN corre como **servicio residente** que lanza los respaldos según el scheduler propio (sin cron ni Task Scheduler). También uso manual puntual (`odin run`) para respaldos ad-hoc o pruebas.

---

## 4. Funcionalidades Principales

### F1. Respaldo de bases de datos Firebird (2.5 → 6)
- Invocación de `gbak` como proceso externo (lo provee la instalación cliente/servidor de Firebird del equipo).
- Configuración por base de datos: cadena de conexión (host/puerto/ruta o alias), usuario, contraseña, rol, charset y ruta del binario `gbak` (auto-detección con override explícito, dado que la ubicación difiere entre Windows y Linux y entre versiones).
- Soporte de múltiples bases de datos en una misma ejecución (lista en el JSON).
- Nombre de archivo de salida con convención predecible: `<nombre_bd>_<timestamp>.fbk`.
- Captura de la salida de `gbak`, detección de errores y validación de que el archivo de respaldo fue generado y no está vacío.
- Opciones `gbak` esenciales exponibles (p. ej. modo de transporte/backup, ignición de checksums cuando corresponda), sin aspirar a cubrir el 100% de flags exóticos.

### F2. Compresión 7z
- Compresión del `.fbk` a `.fbk.7z` con **7z**.
- Nivel de compresión configurable en el JSON.
- Decisión de implementación: utilizar la librería Python **py7zr** (implementación pura de 7z) como mecanismo principal, para no depender de instalar 7-Zip/p7zip en cada servidor; se evaluará en el roadmap un modo alternativo que invoque el binario `7z`/`7zz` cuando exista (mejor rendimiento en respaldos muy grandes).
- Opcional (deseable, no bloqueante): cifrado AES-256 con contraseña del propio archivo 7z.

### F3. Configuración y autenticación en JSON legible
- Un único archivo JSON (ruta indicada por argumento de la CLI y/o variable de entorno) con:
  - Lista de bases de datos a respaldar.
  - Lista de **servidores SFTP destino**: nombre, host, puerto, usuario, método de autenticación (**contraseña** o **clave privada** con passphrase opcional), ruta remota de destino.
  - **Casilla de correo de control** (`to`) y parámetros SMTP (host, puerto, TLS/STARTTLS, credenciales, remitente).
  - Parámetros de compresión, directorio de trabajo y retención local.
- El formato debe ser **legible por humanos** (requisito explícito del proyecto).
- El esquema es **OS-agnóstico**: mismo JSON en Windows y Linux; las rutas se normalizan con `pathlib`, aceptan `/` o `\`, soportan `~` y pueden ser relativas al archivo de configuración (ver ejemplos por plataforma en la sección 5).
- Subcomando de **validación** del JSON (estructura, conectividad básica, rutas) con mensajes de error claros antes de ejecutar.

### F4. Transferencia SFTP con paramiko
- Librería de transferencia: **paramiko** (requisito excluyente).
- Envío del archivo `.fbk.7z` a **cada servidor** de la lista, con autenticación por contraseña o clave privada según el JSON.
- Creación de directorios remotos si no existen.
- Verificación post-transferencia (tamaño del archivo remoto vs. local).
- Reintentos configurables ante fallos transitorios de red.
- Un servidor caído **no aborta** la ejecución completa: se continúa con el resto y el fallo queda reflejado en el informe y en el correo.

### F5. Notificación por correo electrónico
- Al terminar la ejecución (éxito total, éxito parcial o fallo), envío de un correo a la casilla de control definida en el JSON.
- Contenido del correo: estado global, bases respaldadas, tamaño original/comprimido, tiempo de duración, servidores destino con resultado individual (OK/FALLO y motivo), y errores relevantes.
- Envío por SMTP (soporte de STARTTLS/SSL y autenticación) usando la estructura de configuración del JSON.
- El correo **nunca** incluye credenciales ni el archivo de respaldo como adjunto.

### F6. CLI y operación
- Punto de entrada único (script de consola registrado en `pyproject.toml`), p. ej.:
  - `odin run --config ruta/config.json` — ejecución completa puntual (one-shot).
  - `odin validate --config ruta/config.json` — validación de configuración y conectividad.
  - `odin service ...` — comandos de gestión del modo servicio (ver F7).
- Códigos de salida diferenciados (0 = OK, distintos de 0 según tipo de fallo) para integración con monitoreo.
- Logging estructurado a archivo (con rotación) y a consola; nivel configurable.

### F7. Scheduler propio y ejecución como servicio
- **Scheduler interno** configurado desde el JSON (horarios por base de datos o global, sintaxis tipo cron o hora/día explícita, con zona horaria) que dispara el flujo completo de respaldo sin depender de cron/Task Scheduler.
- **Modo servicio residente**:
  - **Windows Server:** instalación/desinstalación como Windows Service (p. ej. `odin service install|uninstall|start|stop`) con reinicio automático ante caída.
  - **Linux LTS:** ejecución como daemon en primer plano (`odin service run`) acompañado de una unit de systemd de referencia provista por el proyecto (la unit solo supervisa; la programación la hace el scheduler interno).
- Comportamiento del scheduler:
  - Ejecuciones solapadas: si un job sigue corriendo al llegar su próximo horario, el nuevo disparo se omite o se encola (configurable), nunca se duplican respaldos simultáneos de la misma base.
  - Job perdido por downtime (misfire): política configurable de ejecución al recuperar el servicio o descarte.
  - Recarga de configuración sin reiniciar el servicio (señal/comando) o reinicio controlado ante cambio del JSON.
  - Estado consultable (`odin service status`): última ejecución, próximo disparo, salud.
- El modo servicio mantiene las mismas garantías de logging, notificación y manejo de errores que `odin run`.

### F8. Retención local (función secundaria)
- Limpieza opcional de respaldos/comprimidos locales según política configurable (días o cantidad), para evitar llenar el disco del servidor de origen. El envío remoto no elimina automáticamente el archivo local salvo configuración explícita.

---

## 5. Arquitectura Técnica

### Stack
| Componente | Elección | Justificación |
|---|---|---|
| Lenguaje | Python ≥ 3.14 | Ya fijado en `pyproject.toml` (`.python-version = 3.14`) |
| Gestión/instalación | **uv** (`uv tool install` / `uvx` / `uv run`) | Requisito del proyecto; instalación homogénea y rápida en Windows y Linux |
| Respaldo Firebird | `gbak` (binario externo, subprocess) | Es la herramienta oficial y soportada para backup lógico en todas las versiones 2.5–6 |
| Compresión | **py7zr** (principal); binario 7z opcional a futuro | Evita dependencias de SO; instalable puramente vía uv |
| Transferencia | **paramiko** (SFTP sobre SSH) | Requisito excluyente del proyecto |
| Correo | `smtplib` + `email` (stdlib) | Sin dependencias adicionales para SMTP simple |
| Scheduler | APScheduler (o implementación propia con stdlib) | Scheduler robusto, con semántica cron/misfire y sin necesidad de planificador del SO |
| Servicio Windows | `pywin32` | Registro/operación como Windows Service nativo |
| CLI/Config | argparse o typer + `json` (stdlib) | Mantener dependencias mínimas |
| Tests | pytest | Estándar de facto |

### Flujo de ejecución

```
Carga y validación del JSON de configuración
        │
        ▼
Por cada base de datos:
   gbak -b  ──►  <bd>_<ts>.fbk
        │
        ▼
   Compresión 7z  ──►  <bd>_<ts>.fbk.7z
        │
        ▼
   Por cada servidor SFTP (paramiko):
        upload + verificación (reintentos)
        │
        ▼
Recopilación de resultados (éxito / parcial / fallo)
        │
        ▼
Envío de correo a la casilla de control (siempre)
        │
        ▼
Limpieza/retención local (si está configurada) → exit code
```

En **modo servicio**, el scheduler interno repite este flujo completo según los horarios configurados; cada ciclo es independiente y genera su propia notificación. En modo one-shot (`odin run`) el flujo se ejecuta una única vez y el proceso termina con su exit code.

### Estructura JSON de referencia (contrato de configuración)

El esquema es **idéntico en ambas plataformas**; lo único que cambia son los valores de rutas. Para mantener el contrato OS-agnóstico, ODIN aplica estas convenciones:

- **Normalización de rutas locales:** se usa `pathlib` internamente; se aceptan separadores `/` y `\` indistintamente y se normalizan al SO actual.
- **`~` expandible:** los paths locales pueden usar `~` / `~/...` (se expande con el home del usuario del servicio).
- **Rutas relativas:** se resuelven respecto de la ubicación del archivo JSON de configuración (portables entre servidores).
- **`connection`:** es la cadena de conexión Firebird y su formato depende del SO **donde reside la base de datos** (path POSIX en Linux, letra de unidad en Windows), no del SO donde corre ODIN.
- **`remote_path`:** sigue la convención del **servidor destino** (SFTP), no la del origen.
- **`gbak_path`:** en `null` se auto-detecta según SO y versión de Firebird instalada.
- En JSON, las barras invertidas de Windows se escriben escapadas (`\\`).

#### Ejemplo Linux LTS

```json
{
  "databases": [
    {
      "name": "nombre_clave_sistema",
      "connection": "localhost/3050:/var/lib/firebird/data/erp.fdb",
      "user": "SYSDBA",
      "password": "***",
      "role": null,
      "charset": "ISO8859_1",
      "gbak_path": null
    }
  ],
  "compression": {
    "level": 7,
    "password": null
  },
  "servers": [
    {
      "name": "sitio-alterno-1",
      "host": "203.0.113.10",
      "port": 22,
      "username": "odin",
      "auth": { "method": "password", "password": "***" },
      "remote_path": "/backups/firebird/"
    },
    {
      "name": "sitio-alterno-2",
      "host": "backup.example.com",
      "port": 2222,
      "username": "odin",
      "auth": { "method": "key", "private_key": "~/.ssh/id_ed25519", "passphrase": null },
      "remote_path": "/srv/backups/firebird/"
    }
  ],
  "notification": {
    "to": "control@example.com",
    "from": "odin-backups@example.com",
    "smtp": {
      "host": "smtp.example.com",
      "port": 587,
      "starttls": true,
      "username": "odin-backups@example.com",
      "password": "***"
    }
  },
  "local": {
    "work_dir": "/var/backups/odin",
    "retention_days": 7
  },
  "scheduler": {
    "enabled": true,
    "timezone": "America/Argentina/Buenos_Aires",
    "jobs": [
      {
        "databases": ["nombre_clave_sistema"],
        "schedule": "0 2 * * *",
        "on_misfire": "run_once",
        "skip_if_running": true
      }
    ]
  }
}
```

#### Ejemplo Windows Server

```json
{
  "databases": [
    {
      "name": "nombre_clave_sistema",
      "connection": "localhost/3050:C:\\Datos\\ERP\\erp.fdb",
      "user": "SYSDBA",
      "password": "***",
      "role": null,
      "charset": "ISO8859_1",
      "gbak_path": null
    }
  ],
  "compression": {
    "level": 7,
    "password": null
  },
  "servers": [
    {
      "name": "sitio-alterno-1",
      "host": "203.0.113.10",
      "port": 22,
      "username": "odin",
      "auth": { "method": "password", "password": "***" },
      "remote_path": "/backups/firebird/"
    },
    {
      "name": "sitio-alterno-2",
      "host": "backup.example.com",
      "port": 2222,
      "username": "odin",
      "auth": { "method": "key", "private_key": "~/.ssh/id_ed25519", "passphrase": null },
      "remote_path": "/srv/backups/firebird/"
    }
  ],
  "notification": {
    "to": "control@example.com",
    "from": "odin-backups@example.com",
    "smtp": {
      "host": "smtp.example.com",
      "port": 587,
      "starttls": true,
      "username": "odin-backups@example.com",
      "password": "***"
    }
  },
  "local": {
    "work_dir": "D:\\Backups\\odin",
    "retention_days": 7
  },
  "scheduler": {
    "enabled": true,
    "timezone": "America/Argentina/Buenos_Aires",
    "jobs": [
      {
        "databases": ["nombre_clave_sistema"],
        "schedule": "0 2 * * *",
        "on_misfire": "run_once",
        "skip_if_running": true
      }
    ]
  }
}
```

> Alternativa portable: con la convención de rutas relativas, `"work_dir": "./work"` y `"private_key": "~/.ssh/id_ed25519"` funcionan sin cambios en ambas plataformas.

### Despliegue
- Instalación: `uv tool install odin` (o equivalente desde el repositorio) en el servidor de origen.
- **La programación de horarios es interna**: ODIN corre como servicio residente con su propio scheduler (F7). No requiere cron ni tareas programadas del SO.
  - Windows Server: `odin service install` registra el Windows Service; el arranque es automático con el sistema.
  - Linux LTS: se provee una unit de systemd de referencia cuyo único rol es mantener vivo el proceso `odin service run` (arranque en boot y reinicio ante caída).
- El modo one-shot (`odin run`) queda disponible como alternativa si un sitio prefiere un planificador externo, pero no es la modalidad principal.
- Requisito en el servidor de origen: cliente o servidor Firebird instalado (aporta `gbak`).

---

## 6. Requisitos No Funcionales

- **Confiabilidad:** reintentos de red configurables; un destino fallido no invalida el resto; la notificación de fallo se envía incluso cuando falla la transferencia (solo un fallo catastrófico de SMTP podría impedirlo, y debe quedar en log con exit code ≠ 0). El servicio residente debe recuperarse solo tras reinicios del SO y ante caídas (auto-arranque/auto-reinicio), y el scheduler no debe duplicar respaldos ni perder disparos sin dejar rastro en el log.
- **Seguridad:**
  - Nunca loguear contraseñas ni claves privadas; enmascarado de secretos en logs y correos.
  - El JSON contiene credenciales en texto legible (decisión explícita del proyecto): se documentará como riesgo y se exigirá restringir permisos del archivo (p. ej. `600` en Linux, ACL en Windows) y excluirlo de control de versiones.
  - Soporte de autenticación SFTP por clave privada como alternativa recomendada a contraseñas.
  - Verificación de host keys SSH configurable (política por defecto segura pero operable en entornos internos).
- **Portabilidad:** misma base de código para Windows Server (2016 o superior) y Linux LTS (Ubuntu LTS, Debian stable, RHEL/Rocky/AlmaLinux soportadas). Manejo explícito de rutas, separadores y ubicación de `gbak` por plataforma.
- **Observabilidad:** log por ejecución con timestamps, duración y detalle de errores; salida estándar apta para ser capturada por el planificador.
- **Rendimiento:** compresión y transferencia acotadas por configuración (nivel de compresión, timeouts); el proceso no debe bloquearse indefinidamente (timeouts en gbak, SFTP y SMTP).
- **Mantenibilidad:** código simple y testeable (pytest), dependencias mínimas, documentación de uso con ejemplos reales.

---

## 7. Restricciones y Supuestos

### Restricciones
- **paramiko** es obligatorio para la transferencia (no evaluar otras librerías SFTP).
- Instalación únicamente vía **uv**.
- Python **≥ 3.14** (definido en el repositorio).
- La configuración remota y de notificación vive en **JSON legible**, sin base de datos ni servicios externos.
- El formato de compresión es **7z** (único formato soportado).

### Supuestos
- El servidor donde corre ODIN tiene instalado Firebird (cliente o servidor) y por tanto `gbak` disponible; para respaldar bases remotas, la conectividad de red Firebird (puerto 3050 o el configurado) está abierta.
- Existe conectividad SSH saliente desde el servidor de origen hacia cada destino SFTP.
- Existe un servidor SMTP alcanzable para las notificaciones.
- El usuario de cada destino SFTP tiene permisos de escritura en la carpeta remota configurada.
- Firebird 6 es una versión reciente: la compatibilidad se logra usando el `gbak` de la misma familia de versión que la base (ODIN permite apuntar a binarios `gbak` distintos por base de datos). No se asume soporte de características experimentales de Firebird.
- Los respaldos son de tipo **full** (no se asume necesidad inicial de backups incrementales/diferenciales de `gbak` en el alcance base).
- Se dispone de permisos suficientes para registrar y arrancar el servicio: privilegios de administrador en Windows Server y root/sudo (o una unit systemd preinstalada) en Linux LTS.

---

## 8. Fuera de Alcance

| Excluido | Motivo |
|---|---|
| Interfaz gráfica o web | El proyecto es una CLI desatendida; una UI agrega complejidad sin valor para el caso de uso |
| Restauración (restore) de backups | Es un flujo distinto con sus propios riesgos; podrá ser una extensión futura fuera de esta versión |
| Otros motores de base de datos (PostgreSQL, MySQL, etc.) | El alcance es específicamente Firebird |
| Otros protocolos de envío (FTP plano, rsync, S3, nubes) | El requisito es SFTP/SSH; se evita dispersión de alcance |
| Otros formatos de compresión (zip, gzip, zstd) | El requisito es 7z |
| Gestión de secretos tipo vault/KMS | El requisito explícito es JSON legible; se documentan las mitigaciones de seguridad |
| Agentes remotos o arquitectura distribuida | Modelo simple push desde el origen hacia los destinos |
| Backups incrementales/diferenciales y replicación transaccional | No requeridos en la visión inicial |
| Soporte de plataformas fuera de Windows Server / Linux LTS | Fuera del requisito de instalación |

---

## 9. Criterios de Éxito

1. **Instalación:** `uv tool install` del proyecto funciona sin pasos manuales en un Windows Server limpio y en un Linux LTS limpio con `uv` disponible.
2. **Punta a punta:** sobre una base Firebird real de prueba (se cubren al menos los extremos 2.5 y una versión moderna 5/6), una ejecución de `odin run` produce el `.fbk`, lo comprime a `.7z`, lo deposita correctamente en **todos** los servidores SFTP del JSON y la casilla de control recibe el correo de éxito con el resumen.
3. **Tolerancia a fallos:** si un servidor SFTP está caído, la ejecución continúa con los demás y el correo refleja el estado parcial con el detalle del fallo.
4. **Notificación de error:** ante cualquier fallo (gbak, compresión, todos los destinos, SMTP), el proceso termina con exit code ≠ 0, deja el error en el log y envía el correo de fallo (salvo fallo del propio SMTP).
5. **Validación:** `odin validate` detecta y describe claramente errores de estructura/rutas del JSON antes de ejecutar.
6. **Seguridad básica:** ningún log ni correo contiene contraseñas o claves privadas.
7. **Calidad:** suite de tests automatizados (configuración, compresión, transferencia con dobles de prueba, notificación, scheduler) y documentación de instalación/uso para ambas plataformas.
8. **Modo servicio:** en Windows Server y Linux LTS, ODIN corre como servicio residente con su scheduler propio, dispara los respaldos según el horario del JSON sin cron ni Task Scheduler, se recupera automáticamente tras un reinicio del SO y no duplica ejecuciones de una misma base (solapamiento controlado).

---

## 10. Próximo Paso

Revisar esta visión y, en una **nueva sesión de chat**, ejecutar `/speckit.aide.create-roadmap` para generar el roadmap de desarrollo por etapas.
