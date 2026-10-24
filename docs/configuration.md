# ODIN — Referencia de configuración

Esta guía documenta **todos los campos** del JSON de configuración de ODIN:
tipo, obligatoriedad, valor por defecto, rangos, semántica y reglas de
validación. El contrato se implementa en `src/odin/config.py`; el
comportamiento de consumo corresponde a la versión **1.0.0**.

- Guía rápida y operación: [`README.md`](../README.md#configuración).
- Ejemplos listos para copiar: [`examples/`](../examples/).
- Permisos, claves SSH y host keys: [`docs/security.md`](security.md).
- Resolución de `gbak` por versión: [`docs/firebird.md`](firebird.md).
- Scheduler y servicio residente: [`docs/service.md`](service.md).

> **Nota de alcance:** esta referencia describe lo que el código hace hoy,
> incluidas las limitaciones conocidas de la versión 1.0.0. Los campos
> marcados como *aceptado sin efecto* se validan al cargar, pero todavía no
> influyen en la ejecución; el detalle está en
> [§11](#11-notas-de-implementación-y-límites-conocidos).

---

## Índice

1. [Convenciones del contrato](#1-convenciones-del-contrato)
2. [Estructura del archivo](#2-estructura-del-archivo)
3. [`databases[]`](#3-databases)
4. [`compression`](#4-compression)
5. [`servers[]`](#5-servers)
6. [`notification`](#6-notification)
7. [`local`](#7-local)
8. [`scheduler`](#8-scheduler)
9. [Reglas cruzadas](#9-reglas-cruzadas)
10. [Validación con `odin validate`](#10-validación-con-odin-validate)
11. [Notas de implementación y límites conocidos](#11-notas-de-implementación-y-límites-conocidos)
12. [Ejemplo completo](#12-ejemplo-completo)

---

## 1. Convenciones del contrato

### Ubicación y codificación

- El archivo se indica con `--config <ruta>` o con la variable de entorno
  `ODIN_CONFIG`. Si se pasan ambos, **gana `--config`**.
- Los comandos que necesitan configuración (por ejemplo, `validate`, `run`,
  `service run` e `install`) fallan con exit code `2` si no se indica ninguna
  ruta o si el archivo no se puede leer.
- El contenido debe ser un **objeto JSON** codificado en **UTF-8**, sin
  comentarios ni comas finales.
- El JSON se valida completo al cargarlo: primero la estructura y los tipos y,
  si no hay problemas, las reglas semánticas. Los problemas se acumulan y se
  informan con la ruta exacta del campo (por ejemplo,
  `config.servers[1].auth.private_key`).

### Tipos y valores

| Tipo JSON | Regla |
|---|---|
| `string` | Cadena no vacía. Una cadena compuesta solo por espacios también se rechaza. |
| `integer` | Número entero. Los booleanos (`true`/`false`) y los decimales no cuentan como entero. |
| `number` | Entero o decimal. Los booleanos no cuentan como número. |
| `boolean` | `true` o `false`, sin coerción desde cadenas o números. |
| `array` | Lista JSON; el tipo de sus elementos se valida por campo. |
| `object` | Objeto JSON; las claves desconocidas son error. |

- Los **enums** se comparan de forma exacta y **sensible a mayúsculas**:
  `DEBUG` es válido, `debug` no; `run_once` es válido, `run-once` no.
- Las **rutas locales** se normalizan con `pathlib`: aceptan `/` o `\`,
  expanden `~` y resuelven las rutas relativas contra el **directorio del
  archivo JSON**. En JSON, las barras invertidas de Windows se escriben
  escapadas (`C:\\Datos\\...`).
- No se admite `~` ni resolución de rutas locales en `connection` ni en
  `remote_path`: no son rutas del host donde corre ODIN.

### Obligatorio, opcional, `null` y default

| Situación | Significado |
|---|---|
| **Obligatorio** | La clave debe estar presente; si falta, es un error de configuración. |
| **Opcional** | La clave puede omitirse; se aplica el default de la tabla. |
| **Nullable** | Además de omitirse, acepta `null` explícito, que se interpreta como ausencia de valor (`None`). |
| **Default** | Solo se aplica cuando la clave se **omite**. En un campo no nullable, `null` es un error, no una forma de pedir el default. |

En los campos nullable, `null` tiene un significado propio y documentado:
por ejemplo, `databases[].gbak_path: null` delega la auto-detección y
`local.log_dir: null` usa `<work_dir>/logs`.

### Claves desconocidas y duplicados

- Cualquier clave que no exista en el esquema es un **error**, con sugerencia
  del campo más parecido (`¿quiso decir 'password'?`). Esto aplica en todos
  los niveles: raíz, bases, servidores, autenticación, SMTP, local, scheduler
  y jobs.
- `databases[].name` y `servers[].name` deben ser **únicos** dentro de su
  lista. Un nombre repetido es error.
- `databases` debe contener al menos una base. `servers` puede ser una lista
  vacía: en ese caso las copias quedan solo en `local.work_dir` y `odin
  validate` lo informa como `INFO`.

### Secretos y enmascarado

El JSON contiene credenciales en texto legible por decisión del proyecto.
Se enmascaran en logs, informes, estado y colas de log los valores de:

- `databases[].password`
- `compression.password`
- `servers[].auth.password`
- `servers[].auth.private_key` (la ruta también se considera sensible)
- `servers[].auth.passphrase`
- `notification.smtp.password`

Restringí los permisos del archivo (`600` en Linux; ACL equivalentes en
Windows), no lo versiones y no lo compartas. `odin validate` advierte si el
archivo es legible por grupo u otros en POSIX. Ver
[`docs/security.md`](security.md).

### Unidades

- Los timeouts y esperas son **segundos enteros**, salvo
  `servers[].sftp_retry_backoff_base` y `servers[].sftp_retry_max_delay_sec`,
  que son números decimales en segundos.
- `local.retention_days` está en **días**.
- `local.min_free_mb` está en **MiB**.

---

## 2. Estructura del archivo

Vista de bloques (los comentarios son ilustrativos; el JSON real no los
admite):

```text
{
  "databases":    [ ... ],   // requerido, al menos una base
  "compression":  { ... },   // opcional
  "servers":      [ ... ],   // requerido, puede ser []
  "notification": { ... },   // requerido
  "local":        { ... },   // requerido
  "scheduler":    { ... }    // opcional
}
```

| Bloque | Obligatorio | Contenido |
|---|---|---|
| `databases` | Sí | Bases Firebird a respaldar. |
| `compression` | No | Nivel de 7z y cifrado opcional. |
| `servers` | Sí | Destinos SFTP; puede estar vacío. |
| `notification` | Sí | Casillas y transporte SMTP del informe. |
| `local` | Sí | Directorios, retención y defaults operativos. |
| `scheduler` | No | Horarios y subconjuntos de bases para el modo servicio. |

---

## 3. `databases[]`

Cada elemento describe una base Firebird. `odin run` recorre **todas** las
bases de la lista; los jobs del scheduler eligen subconjuntos por `name`.

| Campo | Tipo | Obligatorio | Default | Reglas y efecto |
|---|---|---|---|---|
| `name` | `string` | Sí | — | No vacío; único en `databases[]`. Es la clave que referencian los jobs y el prefijo del archivo de respaldo. |
| `connection` | `string` | Sí | — | No vacío. Se pasa a `gbak` **tal cual**; el formato depende del SO donde reside la base, no del host de ODIN. |
| `user` | `string` | Sí | — | No vacío. Se pasa como `-user`. |
| `password` | `string` | Sí | — | No vacío. Se pasa como `-password` y se enmascara en logs e informes. |
| `role` | `string \| null` | No | `null` | Si es un texto no vacío, se pasa como `-role`; si es `null`, no se agrega el switch. |
| `charset` | `string \| null` | No | `null` | Se conserva en el modelo, pero **no se pasa a `gbak`**: la herramienta no tiene switch de charset y el respaldo transportable no depende del charset de conexión. |
| `gbak_path` | `string \| null` | No | `null` | Ruta local al ejecutable `gbak`; acepta `~` y rutas relativas al JSON. `null` delega la auto-detección por SO y versión (ver [`docs/firebird.md`](firebird.md)). |
| `gbak_timeout_sec` | `integer \| null` | No | `null` | Entero `> 0`. Si es `null` o se omite, se usa `local.gbak_timeout_sec`. |

### Notas

- **`name` y el nombre del archivo.** El respaldo se guarda como
  `<name>_<YYYYMMDD_HHMMSS>.fbk` y el comprimido como el mismo nombre con
  `.7z`. El parser no valida caracteres especiales: usá un identificador
  simple, sin `/`, `\`, `:` ni otros separadores de ruta, para no crear
  subdirectorios accidentales ni romper la retención (que solo reconoce el
  patrón `<nombre>_<timestamp>.fbk[.7z]`).
- **`connection`.** Ejemplos válidos:
  `localhost/3050:C:\Datos\ERP\erp.fdb` (base en Windows),
  `localhost/3050:/var/lib/firebird/data/erp.fdb` (base en Linux) o un alias
  de Firebird. La guía de Firebird cubre la regla de familia de `gbak`.
- **Timeout.** La precedencia es `databases[].gbak_timeout_sec` y, si es
  `null`, `local.gbak_timeout_sec`. El valor efectivo debe ser mayor que cero.
- **`charset`.** Se mantiene por compatibilidad con el contrato de la visión,
  pero no interviene en la ejecución actual.
- **`role`.** Si es `null`, no se envía. Un `""` no es válido: omitilo o usá
  `null`. Si el servidor exige un rol, usá el nombre exacto.

```json
{
  "name": "erp_principal",
  "connection": "localhost/3050:C:\\Datos\\ERP\\erp.fdb",
  "user": "SYSDBA",
  "password": "***",
  "role": null,
  "charset": "ISO8859_1",
  "gbak_path": null,
  "gbak_timeout_sec": 3600
}
```

---

## 4. `compression`

El bloque es opcional. Si se omite, se usan `level: 7` y `password: null`.

| Campo | Tipo | Obligatorio | Default | Reglas y efecto |
|---|---|---|---|---|
| `level` | `integer` | No | `7` | Entero entre `0` y `9`. `0` = sin compresión (*store*); `1–9` = LZMA2 con `preset` igual al nivel. Mayor nivel = más compresión, más CPU y más memoria. |
| `password` | `string \| null` | No | `null` | Si es un texto no vacío, el contenido del `.fbk.7z` se cifra con 7zAES (AES-256). Si es `null` o se omite, no hay cifrado. Se enmascara. |

### Notas

- El archivo se escribe primero en un temporal del mismo directorio y se
  publica con `os.replace` solo después de validarlo. Una compresión fallida
  no reemplaza una copia anterior.
- El cifrado es **solo del contenido**: no se cifra la cabecera del 7z. Con
  contraseña incorrecta el contenido no se recupera: py7zr falla al descifrar
  (habitualmente `lzma.LZMAError` o `EOFError`) en lugar de devolver los bytes
  originales.
- Nivel `0` no desactiva la creación del `.7z`: genera un archivo 7z en modo
  *store* (sin compresión), no un `.fbk` sin empaquetar.
- La salida se nombra `<name>_<timestamp>.fbk.7z`.

```json
{
  "level": 7,
  "password": null
}
```

---

## 5. `servers[]`

Cada elemento es un destino SFTP. Si la lista está vacía, las copias quedan
solo en `local.work_dir` y `odin validate` lo informa como `INFO`; no es un
error.

| Campo | Tipo | Obligatorio | Default | Reglas y efecto |
|---|---|---|---|---|
| `name` | `string` | Sí | — | No vacío; único en `servers[]`. Identifica el destino en logs, informes y estado. |
| `host` | `string` | Sí | — | No vacío. Hostname o IP; sin esquema `sftp://`. |
| `port` | `integer` | Sí | — | Entero entre `1` y `65535`. |
| `username` | `string` | Sí | — | No vacío. Usuario SSH/SFTP. |
| `auth` | `object` | Sí | — | Objeto de autenticación; ver tabla siguiente. |
| `remote_path` | `string` | Sí | — | No vacío. Directorio remoto POSIX donde se publican los `.fbk.7z`. Se crea de forma recursiva si no existe. Se recomienda **ruta absoluta** y `/` como separador. |
| `host_key_policy` | `string` | No | `"strict"` | `strict`, `known_hosts`, `accept-new` o `insecure`; ver más abajo. |
| `sftp_retries` | `integer` | No | `3` | Entero `>= 0`, pero el ejecutor exige **al menos `1`**. Es la cantidad de **intentos totales** por conexión y subida, no reintentos adicionales. |
| `sftp_connect_timeout_sec` | `integer` | No | `30` | Entero `>= 1`. Timeout de la conexión SSH. |
| `sftp_operation_timeout_sec` | `integer` | No | `60` | Entero `>= 1`. **Aceptado sin efecto en 1.0.0**: no se aplica a las operaciones SFTP. |
| `sftp_retry_backoff_base` | `number` | No | `2.0` | Número `>= 0`. Base del backoff exponencial entre intentos. |
| `sftp_retry_max_delay_sec` | `number` | No | `30.0` | Número `>= 0`. Tope del backoff, en segundos. |

### 5.1 `servers[].auth`

| Campo | Tipo | Obligatorio | Default | Reglas y efecto |
|---|---|---|---|---|
| `method` | `string` | Sí | — | `password` o `key`. Es obligatorio aunque el modelo tenga `password` como valor de arranque. |
| `password` | `string \| null` | Condicional | `null` | Obligatorio y no vacío cuando `method` es `password`. Debe omitirse o ser `null` cuando `method` es `key`. Se enmascara. |
| `private_key` | `string \| null` | Condicional | `null` | Obligatorio y no vacío cuando `method` es `key`. Debe omitirse o ser `null` cuando `method` es `password`. Ruta local: acepta `~` y relativas al JSON. Se enmascara. |
| `passphrase` | `string \| null` | No | `null` | Solo con `method: key`. Si se incluye, debe ser un texto no vacío. Se enmascara. |

Reglas de coherencia:

- `method: password` exige `password` y prohíbe `private_key` y `passphrase`.
- `method: key` exige `private_key` y prohíbe `password`; `passphrase` es
  opcional.
- Los campos opcionales de tipo string no aceptan `""` si están presentes:
  usá `null` u omitilos.

### 5.2 Clave privada

- Debe estar en formato **OpenSSH/PEM y ser una clave RSA**. La versión actual
  carga la clave con `paramiko.RSAKey`; las claves Ed25519 no están
  soportadas.
- El formato PuTTY (`.ppk`) se rechaza con un error explícito. Convertila con
  `puttygen clave.ppk -O private-openssh -o clave_openssh`.
- `odin validate` comprueba que exista, sea legible y tenga permisos
  recomendados (`600`). Ver [`docs/security.md`](security.md#3-autenticación-sftp-clave-privada-frente-a-contraseña).

### 5.3 Política de host keys

| Valor | Comportamiento | Riesgo |
|---|---|---|
| `strict` (default) | Carga las claves conocidas y rechaza las desconocidas. | Ninguno; es la postura recomendada en producción. |
| `known_hosts` | Equivalente explícito de `strict`: carga las claves de sistema y rechaza lo desconocido. | Ninguno. |
| `accept-new` | Acepta y registra la clave en el primer contacto; después rechaza cambios. | Acepta un MITM en la primera conexión. |
| `insecure` | Acepta cualquier clave, incluso si cambió. | MITM silencioso; `odin validate` lo advierte. |

El `known_hosts` que se usa es el del usuario que ejecuta ODIN
(`~/.ssh/known_hosts`), no una ruta configurable. Aprovisiónelo fuera de banda
con `ssh-keyscan` desde un canal confiable. El detalle y las recomendaciones
están en [`docs/security.md`](security.md#4-políticas-de-host-key).

### 5.4 Reintentos, backoff y timeouts

- `sftp_retries` es la cantidad de **intentos totales** de las operaciones
  reintentables (conexión y subida). Con `3`, se hacen hasta tres intentos, no
  cuatro. La creación de directorios y la verificación posterior de tamaño no
  se reintentan por separado.
- Los errores de autenticación **no se reintentan**: fallan de inmediato.
- Ante un error de red/SSH, la espera antes del siguiente intento es
  `min(sftp_retry_backoff_base * 2^intento, sftp_retry_max_delay_sec)`.
  `0` en la base desactiva la espera.
- `sftp_connect_timeout_sec` se pasa al `connect` de Paramiko.
  `sftp_operation_timeout_sec` se acepta y valida, pero la 1.0.0 todavía no lo
  aplica; ver [§11](#11-notas-de-implementación-y-límites-conocidos).
- Un `sftp_retries: 0` pasa el parser pero hace fallar todas las operaciones
  en el ejecutor. Usá `>= 1`.

### 5.5 `remote_path`

- Se usa como directorio remoto: el archivo se publica en
  `posixpath.join(remote_path, nombre_del_archivo)`.
- Se recomienda una ruta **absoluta** (`/backups/firebird/`). Con una ruta
  relativa, la creación recursiva de directorios la interpreta desde la raíz
  `/`, que puede no coincidir con el directorio relativo al home del usuario
  SSH usado para subir el archivo.
- No se expande `~` ni se normalizan separadores `\`: usá `/`.

```json
{
  "name": "sitio-alterno-1",
  "host": "203.0.113.10",
  "port": 22,
  "username": "odin",
  "auth": {
    "method": "password",
    "password": "***"
  },
  "remote_path": "/backups/firebird/",
  "host_key_policy": "strict",
  "sftp_retries": 3,
  "sftp_connect_timeout_sec": 30,
  "sftp_operation_timeout_sec": 60,
  "sftp_retry_backoff_base": 2.0,
  "sftp_retry_max_delay_sec": 30.0
}
```

---

## 6. `notification`

| Campo | Tipo | Obligatorio | Default | Reglas y efecto |
|---|---|---|---|---|
| `to` | `string` | Sí | — | Casilla de control que recibe el informe. Un solo email con formato `usuario@dominio.tld`; el parser rechaza listas y nombres visibles. |
| `from` | `string` | Sí | — | Remitente del informe. Un solo email con el mismo formato. |
| `smtp` | `object` | Sí | — | Transporte SMTP; ver tabla siguiente. |
| `log_tail_lines` | `integer` | No | `50` | Entero `>= 0`. Cantidad de últimas líneas del log que se anexan al cuerpo; `0` desactiva la cola. Las líneas ya van enmascaradas. |

### 6.1 `notification.smtp`

| Campo | Tipo | Obligatorio | Default | Reglas y efecto |
|---|---|---|---|---|
| `host` | `string` | Sí | — | No vacío. Servidor SMTP. |
| `port` | `integer` | Sí | — | Entero entre `1` y `65535`. |
| `starttls` | `boolean` | No | `true` | Negocia STARTTLS antes de autenticar. `false` permite modo plano (relays locales) o SSL implícito junto con `ssl: true`. |
| `ssl` | `boolean` | No | `false` | SSL implícito (típicamente puerto `465`). Es mutuamente excluyente con `starttls: true`. |
| `username` | `string` | Sí (1.0.0) | — | No vacío. Usuario de autenticación SMTP. |
| `password` | `string` | Sí (1.0.0) | — | No vacío. Contraseña de autenticación SMTP; se enmascara. |

### 6.2 Transporte

| `starttls` | `ssl` | Modo | Observación |
|---|---|---|---|
| `true` | `false` | SMTP + STARTTLS | Default. |
| `false` | `false` | SMTP en plano | `odin validate` advierte que las credenciales viajarían sin cifrar. |
| `false` | `true` | SMTP_SSL | SSL implícito, típicamente puerto `465`. |
| `true` | `true` | — | Error de configuración: son mutuamente excluyentes. |

### 6.3 Notas

- El correo se envía **siempre** al terminar una corrida (`odin run` o un ciclo
  del scheduler), con éxito, fallo parcial o fallo total. Un SMTP caído no
  aborta el respaldo: deja el informe como no enviado y degrada el exit code
  cuando corresponde.
- El cuerpo es texto plano; no se adjuntan los respaldos.
- `username` no vacío dispara `AUTH` con `password`. En la 1.0.0 el parser
  exige ambos campos no vacíos; el modelo y el notificador admiten `""` para
  relays sin autenticación, pero esa configuración todavía no es aceptada.
  Ver [§11](#11-notas-de-implementación-y-límites-conocidos).
- El timeout de red del envío SMTP es fijo (30 s) y no se configura en el
  JSON.

```json
{
  "to": "control@example.com",
  "from": "odin-backups@example.com",
  "smtp": {
    "host": "smtp.example.com",
    "port": 587,
    "starttls": true,
    "ssl": false,
    "username": "odin-backups@example.com",
    "password": "***"
  },
  "log_tail_lines": 50
}
```

---

## 7. `local`

| Campo | Tipo | Obligatorio | Default | Reglas y efecto |
|---|---|---|---|---|
| `work_dir` | `string` | Sí | — | No vacío. Directorio local de artefactos y estado. Se crea si no existe. Contiene los `.fbk`, los `.fbk.7z`, `scheduler_state.json` y el archivo de control de recarga. |
| `retention_days` | `integer` | Sí | — | Entero `>= 0`. `0` deshabilita la limpieza; `N > 0` elimina los artefactos gestionados con más de N días de antigüedad. |
| `log_level` | `string` | No | `"INFO"` | `DEBUG`, `INFO`, `WARNING` o `ERROR`. Controla el archivo y la consola. |
| `log_dir` | `string \| null` | No | `null` | Directorio del `odin.log`. Si es `null` o se omite, se usa `<work_dir>/logs`. |
| `min_free_mb` | `integer` | No | `1024` | Entero `>= 0`. Espacio libre mínimo que **comprueba `odin validate`**; no bloquea `odin run`. |
| `gbak_timeout_sec` | `integer` | No | `7200` | Entero `> 0`. Timeout por defecto de cada respaldo cuando la base no define `gbak_timeout_sec`. |
| `sftp_retries` | `integer` | No | `3` | Entero `>= 0`. **Aceptado sin efecto en 1.0.0**: cada servidor usa su propio `sftp_retries`. |
| `sftp_connect_timeout_sec` | `integer` | No | `30` | Entero `> 0`. **Aceptado sin efecto en 1.0.0**: cada servidor usa su propio `sftp_connect_timeout_sec`. |

### 7.1 Directorios

- `work_dir` es la raíz de los artefactos. `odin run` la crea antes de
  respaldar; `odin service run` también la usa para el estado del scheduler.
- `log_dir` se crea al inicializar el logging. El archivo es `odin.log`, con
  rotación fija de 5 MiB por archivo y 5 backups; la rotación no se configura
  en el JSON.
- `odin validate` comprueba que ambos directorios existan, sean creables o no
  entren en conflicto, y omite la comprobación si la ruta es de otro sabor de
  SO (por ejemplo, una ruta Windows en Linux).

### 7.2 Retención

Con `retention_days > 0`, después del correo se eliminan de `work_dir`:

- archivos **regulares** de nivel superior cuyo nombre cumpla
  `<nombre>_<YYYYMMDD_HHMMSS>.fbk` o `<nombre>_<YYYYMMDD_HHMMSS>.fbk.7z`;
- con `mtime` estrictamente anterior a `ahora - retention_days` días;
- que no hayan sido creados por la corrida actual (`mtime >= inicio`).

No se tocan subdirectorios, symlinks, logs, configuración ni archivos con
otros nombres. Un error de borrado se registra y no aborta la corrida. Con
`0` la limpieza queda deshabilitada. `odin validate` informa la política
activa.

### 7.3 `min_free_mb`

`odin validate` consulta el espacio libre en el ancestro existente más cercano
a `work_dir` y compara con `min_free_mb`. Si no alcanza, emite una
**advertencia**; `odin run` no repite esa comprobación. Ajustá el valor según
el tamaño de tus bases y la frecuencia de respaldo.

### 7.4 Timeouts y defaults SFTP

- `local.gbak_timeout_sec` actúa como default; `databases[].gbak_timeout_sec`
  tiene precedencia cuando no es `null`.
- `local.sftp_retries` y `local.sftp_connect_timeout_sec` se aceptan y se
  parsean, pero la 1.0.0 **no los propaga** a los servidores. Configurá los
  valores en cada `servers[]`; sus defaults son `3` y `30` respectivamente.

```json
{
  "work_dir": "/var/backups/odin",
  "retention_days": 7,
  "log_level": "INFO",
  "log_dir": null,
  "min_free_mb": 1024,
  "gbak_timeout_sec": 7200,
  "sftp_retries": 3,
  "sftp_connect_timeout_sec": 30
}
```

---

## 8. `scheduler`

El bloque es opcional. Si se omite, el scheduler queda deshabilitado y solo
está disponible el modo one-shot (`odin run`).

| Campo | Tipo | Obligatorio | Default | Reglas y efecto |
|---|---|---|---|---|
| `enabled` | `boolean` | No | `false` | Habilita el scheduler interno. `odin service run` exige `true`; con `false` devuelve exit `2`. |
| `timezone` | `string` | No | `"UTC"` | Nombre IANA (por ejemplo, `America/Argentina/Buenos_Aires`). Se valida con `zoneinfo`/`tzdata`; interpreta los `schedule` y los próximos disparos. |
| `jobs` | `array` | No | `[]` | Lista de jobs. Si `enabled` es `true` y no hay jobs, `odin validate` advierte que no se ejecutará ningún respaldo programado. |

### 8.1 `scheduler.jobs[]`

| Campo | Tipo | Obligatorio | Default | Reglas y efecto |
|---|---|---|---|---|
| `databases` | `array<string>` | Sí | — | Lista no vacía de nombres de bases; cada uno debe existir en `databases[]`. Un job respalda solo ese subconjunto. |
| `schedule` | `string` | Sí | — | Expresión cron de **5 campos** (minuto, hora, día del mes, mes, día de la semana). No admite segundos ni `@reboot`. Se valida con `CronTrigger.from_crontab`. |
| `on_misfire` | `string` | No | `"run_once"` | `run_once`: recupera y ejecuta el disparo vencido; `skip`: lo descarta si llega más de 1 segundo tarde. |
| `skip_if_running` | `boolean` | No | `true` | `true`: si alguna base del job está en ejecución, se omite el ciclo completo. `false`: corre solo con las bases libres y omite las ocupadas. |

### 8.2 Semántica

- **`schedule`.** Es un crontab clásico de cinco campos. Por ejemplo,
  `"0 2 * * *"` = todos los días a las 02:00 en `timezone`. `odin validate`
  calcula el próximo disparo y advierte si la expresión no tiene ninguno
  (por ejemplo, `0 0 31 2 *`).
- **Solapamiento.** Cada job tiene `max_instances=1` y los disparos perdidos se
  agrupan (`coalesce`). Además, `skip_if_running` coordina jobs que comparten
  bases: con `true` el job es todo-o-nada; con `false` reserva solo las bases
  libres y nunca duplica una base en dos ciclos simultáneos.
- **Misfire.** Con `on_misfire: run_once`, un disparo que llega tarde se
  ejecuta igual. Con `skip`, si llega más de 1 segundo después del disparo
  esperado, se descarta y queda registrado como ciclo omitido.
- **Modo servicio.** `odin service run` y el servicio residente usan este
  bloque; `odin run` lo ignora y procesa todas las bases una vez.
- **Recarga.** `odin service reload` vuelve a cargar y validar el JSON y
  re-registra los jobs en caliente, sin reiniciar el proceso. Un JSON inválido
  conserva la configuración vigente.

```json
{
  "enabled": true,
  "timezone": "America/Argentina/Buenos_Aires",
  "jobs": [
    {
      "databases": ["erp_principal", "erp_sucursal"],
      "schedule": "0 2 * * *",
      "on_misfire": "run_once",
      "skip_if_running": true
    }
  ]
}
```

Más detalle de operación, estado y recarga:
[`docs/service.md`](service.md).

---

## 9. Reglas cruzadas

Además de los tipos y rangos de cada tabla, al cargar se verifican:

1. **Nombres únicos** en `databases[]` y `servers[]`.
2. **Referencias de jobs**: cada nombre de `scheduler.jobs[].databases` debe
   existir en `databases[]`.
3. **Coherencia de autenticación**:
   - `method: password` exige `password` y prohíbe `private_key`/`passphrase`;
   - `method: key` exige `private_key` y prohíbe `password`.
4. **STARTTLS/SSL**: `notification.smtp.starttls: true` y
   `notification.smtp.ssl: true` son incompatibles.
5. **Campos desconocidos**: se rechazan en todos los niveles, con sugerencia
   de typo.
6. **Listas mínimas**: `databases` no puede estar vacía; la lista `databases`
   de un job tampoco.
7. **Tipos estrictos**: no hay coerción de `"3"` a `3`, de `1` a `true` ni de
   `"yes"` a `true`.
8. **Rutas**: `work_dir`, `log_dir`, `gbak_path` y `private_key` se normalizan;
   `connection` y `remote_path` no.

Los problemas estructurales se acumulan y se informan juntos. Si la estructura
es válida, se aplican las reglas semánticas y también se informan todas juntas.
Cada mensaje incluye la ruta del campo (`config....`) y el motivo.

---

## 10. Validación con `odin validate`

`odin validate` primero carga el JSON con las reglas de esta guía y después
comprueba el entorno local **sin usar la red**; las verificaciones son de solo
lectura. Al final configura el logging, que puede crear `local.log_dir` y
`odin.log` (y, si `log_dir` es el derivado, también `local.work_dir`):

| Verificación | Qué mira |
|---|---|
| Archivo | Permisos POSIX recomendados (`600`); en Windows se omite con un `INFO` porque las ACL no son portables. |
| `local.work_dir` | Existencia, creabilidad o conflicto con un archivo. |
| `local.log_dir` | Existencia/creabilidad; si es `null`, informa el derivado `<work_dir>/logs`. |
| `local.min_free_mb` | Espacio libre en el ancestro existente más cercano a `work_dir`. |
| `databases[].gbak_path` | Existencia, que no sea un directorio y permisos de ejecución (solo si es explícito). |
| `servers[].auth.private_key` | Existencia, legibilidad y permisos recomendados (solo con `method: key`). |
| `host_key_policy: insecure` | Advertencia de MITM. |
| SMTP sin cifrar | Advertencia si `starttls: false` y `ssl: false`. |
| Scheduler | Bases no cubiertas por ningún job, scheduler habilitado sin jobs, próximo disparo de cada cron. |
| Retención | `retention_days: 0` se informa como limpieza deshabilitada. |

- Los hallazgos se agrupan en `ERRORES`, `ADVERTENCIAS` y `VERIFICACIONES`, y
  cada uno indica el campo implicado.
- Sin `--strict`, las advertencias no invalidan la configuración (exit `0`).
  Con `--strict`, cualquier advertencia devuelve exit `2`.
- Un error de estructura, tipo, rango o regla cruzada devuelve exit `2`.
- La validación **no** comprueba conectividad con Firebird, SFTP ni SMTP; un
  destino caído no invalida el JSON.

```bash
odin validate --config /etc/odin/config.json
odin validate --config /etc/odin/config.json --strict
```

Los exit codes completos están en el
[README](../README.md#exit-codes).

---

## 11. Notas de implementación y límites conocidos

Estas son las diferencias entre el contrato ideal y lo que la versión 1.0.0
aplica realmente. Se documentan para que la configuración no prometa efectos
que hoy no existen.

| Campo o situación | Estado en 1.0.0 | Detalle |
|---|---|---|
| `databases[].charset` | Aceptado, no usado | Se conserva en el modelo; `gbak` no tiene switch de charset y no se pasa. |
| `local.sftp_retries` | Aceptado, no usado | Cada `servers[]` usa su propio `sftp_retries` (default `3`). |
| `local.sftp_connect_timeout_sec` | Aceptado, no usado | Cada `servers[]` usa su propio `sftp_connect_timeout_sec` (default `30`). |
| `servers[].sftp_operation_timeout_sec` | Aceptado, no aplicado | No se configura en el canal SFTP de Paramiko; el único timeout que se aplica es `sftp_connect_timeout_sec`. |
| `servers[].sftp_retries: 0` | Pasa el parser, falla al ejecutar | El ejecutor exige `>= 1` y aborta la operación con un `ConnectionError`. Usá `>= 1`. |
| `notification.smtp.username` / `.password` | Requeridos por el parser | El modelo y el notificador admiten `""` para relays sin AUTH, pero el parser rechaza la omisión o el vacío. Mientras tanto, usá un relay con autenticación. |
| `local.log_level: "CRITICAL"` | No soportado | El enum solo acepta `DEBUG`, `INFO`, `WARNING` y `ERROR`. |
| `local.min_free_mb` | Solo `odin validate` | No bloquea ni condiciona `odin run`; es una advertencia temprana. |
| `databases[].name` | Sin validación de caracteres | Se usa como prefijo del nombre de archivo. Evitá separadores de ruta y caracteres inválidos del sistema de archivos. |
| `servers[].remote_path` relativo | Aceptado, no recomendado | La creación de directorios lo interpreta desde `/`; usá una ruta absoluta para evitar discrepancias. |

Si necesitás uno de estos comportamientos en producción, verificalo contra la
versión instalada antes de depender de él y considerá abrir un cambio en el
proyecto.

---

## 12. Ejemplo completo

Ejemplo Linux con todos los bloques y campos. Reemplazá los `***` y las rutas
por tus valores reales. Para Windows, cambiá `work_dir` y `connection` por
rutas con letra de unidad (con `\\` en el JSON); el resto del esquema es
idéntico.

```json
{
  "databases": [
    {
      "name": "erp_principal",
      "connection": "localhost/3050:/var/lib/firebird/data/erp.fdb",
      "user": "SYSDBA",
      "password": "***",
      "role": null,
      "charset": "ISO8859_1",
      "gbak_path": null,
      "gbak_timeout_sec": null
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
      "auth": {
        "method": "password",
        "password": "***"
      },
      "remote_path": "/backups/firebird/",
      "host_key_policy": "strict",
      "sftp_retries": 3,
      "sftp_connect_timeout_sec": 30,
      "sftp_operation_timeout_sec": 60,
      "sftp_retry_backoff_base": 2.0,
      "sftp_retry_max_delay_sec": 30.0
    },
    {
      "name": "sitio-alterno-2",
      "host": "backup.example.com",
      "port": 2222,
      "username": "odin",
      "auth": {
        "method": "key",
        "private_key": "~/.ssh/id_rsa",
        "passphrase": null
      },
      "remote_path": "/srv/backups/firebird/",
      "host_key_policy": "known_hosts",
      "sftp_retries": 5,
      "sftp_connect_timeout_sec": 30,
      "sftp_operation_timeout_sec": 60,
      "sftp_retry_backoff_base": 2.0,
      "sftp_retry_max_delay_sec": 30.0
    }
  ],
  "notification": {
    "to": "control@example.com",
    "from": "odin-backups@example.com",
    "smtp": {
      "host": "smtp.example.com",
      "port": 587,
      "starttls": true,
      "ssl": false,
      "username": "odin-backups@example.com",
      "password": "***"
    },
    "log_tail_lines": 50
  },
  "local": {
    "work_dir": "/var/backups/odin",
    "retention_days": 7,
    "log_level": "INFO",
    "log_dir": null,
    "min_free_mb": 1024,
    "gbak_timeout_sec": 7200,
    "sftp_retries": 3,
    "sftp_connect_timeout_sec": 30
  },
  "scheduler": {
    "enabled": true,
    "timezone": "America/Argentina/Buenos_Aires",
    "jobs": [
      {
        "databases": ["erp_principal"],
        "schedule": "0 2 * * *",
        "on_misfire": "run_once",
        "skip_if_running": true
      }
    ]
  }
}
```

Antes de ejecutar, validá el archivo:

```bash
odin validate --config ruta/al/config.json
```

Los ejemplos mantenidos en el repositorio son
[`examples/config.linux.json`](../examples/config.linux.json) y
[`examples/config.windows.json`](../examples/config.windows.json).
