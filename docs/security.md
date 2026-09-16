# ODIN — Guía de seguridad

Esta guía explica qué protege ODIN, qué no, y cómo desplegarlo sin exponer
credenciales. Está pensada para quien instala y opera el respaldo: administra
el host, la configuración y las cuentas con las que corre el pipeline.

- Decisión de fondo: [`§1`](#1-modelo-de-amenazas-y-decisión-de-diseño).
- Permisos del JSON: [`§2`](#2-permisos-del-archivo-de-configuración).
- Claves SSH y host keys: [`§3`](#3-autenticación-sftp-clave-privada-frente-a-contraseña) y [`§4`](#4-políticas-de-host-key).
- Enmascarado y sus límites: [`§5`](#5-enmascarado-de-secretos-garantías-y-límites).
- Checklist y rotación: [`§8`](#8-checklist-de-despliegue-seguro) y [`§9`](#9-rotación-de-credenciales).

Documentación relacionada: [`README.md`](../README.md),
[`docs/service.md`](service.md) (cuenta del servicio y permisos de rutas) y
[`examples/README.md`](../examples/README.md).

---

## 1. Modelo de amenazas y decisión de diseño

### Activos a proteger

| Activo | Dónde vive | Impacto si se filtra |
|---|---|---|
| Credenciales Firebird (`databases[].user`/`password`) | JSON de configuración | Acceso total a las bases respaldadas |
| Credenciales SFTP (`servers[].auth`) y passphrase de la clave | JSON + clave privada en disco | Acceso al servidor de respaldos y a todas sus copias |
| Credenciales SMTP (`notification.smtp`) | JSON | Uso del relé para correo no deseado / suplantación |
| Contenido de los respaldos (`.fbk` y `.fbk.7z`) | `local.work_dir` y servidores SFTP | Los datos completos de la base |
| Configuración (rutas, horarios, destinos) | JSON y `scheduler_state.json` | Reconocimiento para un ataque dirigido |

### Superficie de amenaza

- **Usuario local sin privilegios en el mismo host**: puede leer cualquier
  archivo que no esté restringido (JSON, logs, estado).
- **Otro proceso o servicio del host**: ídem; el log y el estado suelen quedar
  legibles con el umask por defecto.
- **Acceso físico o copia de seguridad del host**: un disco o backup del host
  incluye el JSON y los `.fbk`.
- **Red**: intercepción o manipulación de SFTP, SMTP y de la conexión a
  Firebird.
- **Error operativo**: versionar el JSON real, compartirlo por chat/correo o
  dejarlo con permisos abiertos.

### La decisión: credenciales en JSON legible

ODIN guarda los secretos en el **JSON de configuración en texto legible**, por
decisión explícita:

- La configuración es **auditable**: un solo archivo muestra todo lo que el
  respaldo usa.
- Es **OS-agnóstica y sin dependencias**: no requiere vault, KMS, variables de
  entorno por servicio ni un agente de secretos (fuera del alcance de la
  visión).
- La operación es **predecible**: `odin validate`, `odin run` y el servicio
  leen la misma fuente.

Contrapartida: cualquier sujeto con acceso de lectura al archivo obtiene los
secretos. Las mitigaciones son de entorno —permisos, cuenta dedicada,
enmascarado, rotación— y son el resto de esta guía.

### Qué no cubre ODIN

- No cifra el JSON ni los respaldos (el cifrado AES-256 de `.fbk.7z` es
  opcional y protege el artefacto, no la configuración).
- No es un gestor de secretos ni rota credenciales por sí solo.
- No verifica el certificado TLS del servidor SMTP (ver
  [`§6`](#6-correo-tls-y-ssl)).
- No autentica la conexión a Firebird más allá de lo que hace `gbak`.

---

## 2. Permisos del archivo de configuración

El JSON contiene credenciales en texto legible: debe ser legible **solo por su
dueño** (o por la cuenta que corre el servicio).

### Linux

```bash
sudo install -o odin -g odin -m 600 /dev/null /etc/odin/config.json  # crear vacío con permisos
sudo chown odin:odin /etc/odin/config.json
sudo chmod 600 /etc/odin/config.json
sudo chmod 750 /etc/odin                     # el directorio, sin listado para otros
```

Recomendaciones:

- `600` (`rw-------`) para el archivo y `750` para el directorio contenedor.
- Si administra el archivo con un usuario y el servicio corre con otro, el
  dueño puede ser el administrador con grupo `odin` y modo `640`
  (`rw-r-----`): el grupo lee, otros no.
- No lo deje en `/tmp` ni en directorios con `sticky`+lectura global; use
  `/etc/odin/` (o el directorio de la aplicación).

### Windows Server

Las ACL mandan; el modo POSIX no aplica. Para dejar el archivo solo en manos
de los administradores, `SYSTEM` y la cuenta del servicio:

```powershell
icacls C:\odin\config.json /inheritance:r
icacls C:\odin\config.json /grant:r "BUILTIN\Administrators:(F)" "NT AUTHORITY\SYSTEM:(F)"
icacls C:\odin\config.json /grant:r "ODIN_SVC:(R)"    # cuenta del servicio, solo lectura
icacls C:\odin\config.json
```

Notas:

- `/inheritance:r` corta la herencia del directorio (imprescindible: sin eso,
  una carpeta con `Users` vuelve a abrir el archivo).
- Los nombres de grupos integrados se localizan según el idioma del sistema;
  verifique los suyos con `icacls C:\odin\config.json` o use SIDs.
- Dé a la cuenta del servicio **solo lectura** (`:(R)`); el archivo no
  necesita escritura en operación normal.
- La instalación por defecto del servicio usa `LocalSystem`
  ([`docs/service.md` §4](service.md)); si usa una cuenta dedicada, su ACL es
  la que importa.

### Control de versiones y copias

- El JSON **real no se versiona**: el repositorio trae solo
  [`examples/`](../examples/) con placeholders `***`. `.gitignore` ya excluye
  `*.log` y artefactos de prueba, pero no adivina su archivo: no lo agregue
  nunca (`git add -f`).
- No comparta el JSON por chat, correo ni tickets; para transferirlo, use un
  canal cifrado y bórrelo después.
- Si el host se respalda, aplique la misma restricción a la copia de
  seguridad del archivo (o exclúyalo del respaldo y guarde los secretos en un
  gestor aparte).

### Qué reporta `odin validate`

`odin validate` comprueba los permisos y avisa (nunca bloquea):

| Situación | Hallazgo |
|---|---|
| POSIX, modo con bits de grupo/otros (p. ej. `644`) | `ADVERTENCIA`: "se recomienda 600 (contiene credenciales en texto legible)"; el mensaje apunta a esta guía. |
| POSIX, modo `600`/`640` sin acceso de otros | `OK`: "sin acceso de grupo/otros". |
| Clave privada SFTP con acceso de grupo/otros | `ADVERTENCIA`: se recomienda `600`. |
| Windows | `INFO`: la verificación de permisos se omite (las ACL no son comprobables de forma portable); se recuerda restringir el acceso. |
| No se pudo leer el `stat` | `INFO`: no se pudieron comprobar los permisos. |

---

## 3. Autenticación SFTP: clave privada frente a contraseña

`servers[].auth.method` acepta `password` o `key`. Para producción se
recomienda **clave privada con passphrase**:

- La contraseña viaja al servidor en cada conexión y queda escrita en el JSON;
  con clave, el servidor nunca ve un secreto reutilizable.
- La passphrase protege la clave en disco: si alguien copia el archivo, sin la
  passphrase no puede usarlo.
- Rotar la clave no obliga a tocar la contraseña de la cuenta SFTP.

### Generar la clave

Hoy ODIN carga la clave con `paramiko.RSAKey`, así que debe ser **RSA**
(las claves Ed25519 no están soportadas todavía):

```bash
ssh-keygen -t rsa -b 4096 -C "odin-backups" -f ~/.ssh/odin_backup
# pide una passphrase: úsela (no deje la clave sin proteger)
chmod 600 ~/.ssh/odin_backup
ssh-copy-id -i ~/.ssh/odin_backup.pub odin@servidor-destino   # o copie la .pub a authorized_keys
```

### Configurar ODIN

```json
{
  "name": "sitio-alterno-1",
  "host": "backup.example.com",
  "port": 22,
  "username": "odin",
  "auth": {
    "method": "key",
    "private_key": "~/.ssh/odin_backup",
    "passphrase": "***"
  },
  "remote_path": "/srv/backups/firebird/",
  "host_key_policy": "strict"
}
```

- `private_key` admite `~` (se expande al usuario que ejecuta) y rutas
  relativas al JSON; `odin validate` verifica que exista, sea legible y tenga
  permisos recomendados.
- La passphrase se enmascara en logs, informes y estado.

### Formato PPK

ODIN **rechaza** las claves en formato PuTTY (`.ppk`) con un error explícito.
Conviértalas a OpenSSH:

```bash
puttygen clave.ppk -O private-openssh -o clave_openssh
```

### Rotación

1. Genere el par nuevo y autorice la clave pública en el servidor SFTP.
2. Actualice `private_key`/`passphrase` en el JSON.
3. `odin validate` y `odin service reload` (o reinicie el servicio).
4. Retire la clave anterior del `authorized_keys` del servidor.

---

## 4. Políticas de host key

Al conectar por SSH, el cliente debe decidir qué hacer si la clave del
servidor es desconocida. `servers[].host_key_policy` controla esa decisión:

| Valor | Comportamiento | Riesgo | Cuándo usarla |
|---|---|---|---|
| `strict` (**default**) | Rechaza claves desconocidas; exige que estén en `known_hosts` | Ninguno (es la postura segura) | Producción; el `known_hosts` se aprovisiona al instalar |
| `known_hosts` | Carga las claves de sistema y rechaza lo desconocido (equivalente explícito de `strict`) | Ninguno | Igual que `strict`, para dejarlo declarado en el JSON |
| `accept-new` | Acepta y registra la clave en el primer contacto; después rechaza cambios | Acepta un MITM **en la primera conexión** | Puesta en marcha, redes controladas; luego aprovisionar `known_hosts` |
| `insecure` | Acepta cualquier clave, incluso si cambió | MITM silencioso: un atacante puede leer/escribir el tráfico SFTP | Pruebas puntuales; `odin validate` lo advierte |

Recomendación: **`strict` en producción**, con el `known_hosts` del host
(`~/.ssh/known_hosts` del usuario del servicio) aprovisionado fuera de banda:

```bash
ssh-keyscan -H servidor-destino >> ~/.ssh/known_hosts   # ejecutado en un canal de confianza
chmod 600 ~/.ssh/known_hosts
```

Un cambio legítimo de clave en el servidor se resuelve quitando la entrada
vieja de `known_hosts` y volviendo a registrarla; un cambio inesperado es una
señal de alerta, no un error a ignorar.

---

## 5. Enmascarado de secretos: garantías y límites

### Garantías

ODIN enmascara los secretos configurados antes de escribirlos en cualquier
destino de salida:

- **Logs** (`odin.log` y consola): un filtro reemplaza por `***` los valores de
  `iter_secret_fields()` —contraseñas de bases, `compression.password`,
  contraseña/passphrase/ruta de la clave SFTP y contraseña SMTP— y vacía los
  bloques PEM (`PRIVATE KEY`) por patrón.
- **Informes por correo**: asunto y cuerpo pasan por el mismo enmascarador.
- **Resúmenes de consola** de `odin run`: líneas de respaldo, transferencia,
  notificación y retención enmascaradas.
- **`scheduler_state.json`**: los mensajes de error y el último ciclo se
  persisten ya enmascarados.

### Límites

Ninguna barrera de enmascarado es perfecta; estos límites son conocidos:

1. **`gbak -password` en la lista de procesos**: mientras corre el respaldo, la
   contraseña de la base aparece como argumento del proceso `gbak` y puede
   verse con `ps -ef`, `htop` o el Administrador de tareas. Mitigaciones:
   - correr el servicio con una **cuenta dedicada** y restringir quién puede
     listar procesos del host;
   - en Linux, montar `/proc` con `hidepid=2` (u opciones equivalentes) para
     que otros usuarios no vean los procesos ajenos;
   - considerar la ventana del respaldo como el momento de máxima exposición y
     rotar la contraseña si el host no es de confianza.
2. **El JSON es legible por diseño**: los permisos de [`§2`](#2-permisos-del-archivo-de-configuración)
   son la única barrera.
3. **Los respaldos contienen los datos completos**: `work_dir` y los destinos
   SFTP merecen los mismos permisos y cifrado de disco que la base de origen;
   `compression.password` es opcional y protege el `.fbk.7z` en tránsito y en
   reposo.
4. **El enmascarado es literal**: reemplaza el valor exacto del secreto. Si un
   secreto se transforma (codificación, URL, trozo) antes de aparecer en un
   mensaje, puede no coincidir; por eso `odin validate` y la revisión de
   `odin.log` siguen siendo la comprobación final.
5. **El log no tiene permisos propios**: `odin.log` se crea con el umask del
   proceso (típicamente `644`). El contenido ya va enmascarado, pero contiene
   rutas y nombres de bases; restrinja el directorio de logs al usuario del
   servicio (`chmod 750`, `chown odin`).

---

## 6. Correo: TLS y SSL

`notification.smtp` define el cifrado del informe:

| Configuración | Efecto | Uso |
|---|---|---|
| `starttls: true` (default) | Negocia STARTTLS y después autentica | Recomendado (puerto 587) |
| `smtp.ssl: true` | SSL implícito desde el inicio | Puerto 465; mutuamente excluyente con `starttls: true` |
| `starttls: false` y `ssl: false` | Todo en plano, incluida la contraseña SMTP | Solo relays locales de confianza; `odin validate` lo advierte |

**Limitación de verificación**: `smtplib` usa el contexto SSL por defecto de
Python (`ssl._create_stdlib_context()`) cuando ODIN no le pasa uno, de modo que
**cifra el canal pero no verifica el certificado del servidor** (acepta
certificados autofirmados o caducados, y un MITM activo puede interceptar). Si
su infraestructura exige validación estricta de certificado, use un relay
autenticado con certificado válido en la red de confianza y valore esta
limitación en su análisis de riesgo. El cifrado sigue evitando la
interceptación pasiva de la contraseña.

El informe **nunca adjunta el backup**: solo texto (estado, detalle por base y
servidor, totales y cola del log enmascarada). El asunto y el cuerpo no
incluyen credenciales.

---

## 7. Mínimo privilegio de la cuenta del servicio

La cuenta que corre el servicio debe tener exactamente lo necesario:

| Permiso | Uso |
|---|---|
| Lectura del JSON | Cargar la configuración |
| Lectura de la clave privada SFTP y `known_hosts` | Autenticación SSH |
| Escritura en `local.work_dir` y el directorio de logs | `.fbk`, `.fbk.7z`, `odin.log`, `scheduler_state.json` |
| Ejecución de `gbak` (o el binario de `gbak_path`) | Respaldo |
| Acceso de red a Firebird, SFTP y SMTP | Pipeline |

No necesita escritura sobre el JSON ni permisos de administrador (excepto para
instalar/desinstalar el servicio, que es una operación puntual).

### Linux

```bash
sudo useradd --system --home /var/lib/odin --shell /usr/sbin/nologin odin
sudo chown -R odin:odin /var/lib/odin /var/log/odin
sudo chmod 750 /var/lib/odin /var/log/odin
```

La unit por defecto corre como `root`; para producción edítela con
`User=odin`/`Group=odin` y recargue (`docs/service.md` §3.2).

### Windows

La instalación por defecto corre como `LocalSystem` (acceso local amplio). Para
una cuenta dedicada, concédale:

- **Iniciar sesión como servicio** (`SeServiceLogonRight`);
- lectura del JSON y de la clave;
- control total (o modificar/escritura) sobre `work_dir` y logs;
- el ajuste del servicio con `sc.exe config odin obj= "DOMINIO\cuenta"
  password= "..."` (`docs/service.md` §4).

### Red

- Firebird en 3050/TCP (o el configurado), SFTP en 22/TCP y SMTP en el puerto
  del bloque `notification.smtp`, solo desde el host del servicio.
- Restrinja el origen del SFTP y del SMTP a la IP del servidor de respaldos
  cuando su infraestructura lo permita.

---

## 8. Checklist de despliegue seguro

- [ ] El JSON real **no está en control de versiones** y sus secretos son los
      definitivos (no placeholders `***`).
- [ ] Permisos del JSON: `600` y dueño correcto (Linux) o ACL sin herencia
      para dueño/cuenta del servicio (Windows).
- [ ] Directorio de logs y `work_dir` restringidos a la cuenta del servicio.
- [ ] SFTP con `auth.method: key` (RSA con passphrase) y `host_key_policy:
      strict` con `known_hosts` aprovisionado.
- [ ] SMTP con `starttls: true` o `smtp.ssl: true` (nunca plano salvo relay
      local de confianza).
- [ ] Cuenta del servicio dedicada y sin login interactivo, con solo los
      permisos de [`§7`](#7-mínimo-privilegio-de-la-cuenta-del-servicio).
- [ ] `compression.password` si los `.fbk.7z` pasan por redes o discos
      compartidos.
- [ ] `odin validate --config …` sin ERRORES y sin las ADVERTENCIAS evitables
      (permisos, SMTP sin cifrar, `host_key_policy: insecure`, retención
      desactivada sin querer).
- [ ] Revisar que `odin.log` no contenga secretos tras la primera corrida real.
- [ ] Plan de rotación de credenciales documentado ([`§9`](#9-rotación-de-credenciales)).

---

## 9. Rotación de credenciales

ODIN permite cambiar credenciales sin detener el servicio: edite el JSON y pida
la recarga en caliente.

1. **Credenciales Firebird** (`databases[].password` o `user`): cámbielas en el
   servidor Firebird, actualice el JSON, `odin validate` y
   `odin service reload`.
2. **Contraseña SFTP**: cámbiela en el servidor, actualice el JSON y recargue.
3. **Clave SSH**: genere el par nuevo, autorice la pública, actualice
   `private_key`/`passphrase`, recargue y retire la clave anterior
   ([`§3`](#3-autenticación-sftp-clave-privada-frente-a-contraseña)).
4. **Contraseña SMTP**: cámbiela en el relé, actualice el JSON y recargue; el
   próximo informe usa la credencial nueva.
5. **Passphrase de compresión** (`compression.password`): al cambiarla, los
   `.fbk.7z` nuevos usan la nueva; conserve la anterior mientras existan
   archivos viejos cifrados con ella (los archivos no se recifran).

En todos los casos:

- Verifique el resultado con `odin validate` y con un `odin run` de prueba (o
  el próximo ciclo del servicio).
- Confirme en `odin.log` y en el correo que no hay errores de autenticación ni
  secretos expuestos.
- Rotar credenciales periódicamente (p. ej. cada 90 días) y de inmediato ante
  sospecha de filtración, cambio de personal o pérdida de un host.
