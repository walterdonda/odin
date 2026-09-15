# Guía de compatibilidad Firebird y `gbak_path`

ODIN respalda bases Firebird **2.5 a 6** ejecutando `gbak` como cliente: el
binario vive en el host donde corre ODIN y se conecta al servidor por red (o
accede al archivo si la base es local). Esta guía fija la **regla de familia**
(`gbak` de la misma versión mayor que la base), explica cómo resolver
`gbak_path` en cada plataforma y reúne las incompatibilidades verificadas al
ejecutar la matriz de integración (`tests/test_firebird_matrix.py`, Item 069).

- Regla rápida: **la versión mayor de `gbak` debe coincidir con la del
  servidor**. En hosts con varias instalaciones Firebird, indicá
  `databases[].gbak_path` por base.
- Guía relacionada: [`docs/service.md`](service.md) (cuenta del servicio y
  accesos al binario) y el [README](../README.md#ejecución-de-respaldos-odin-run).

---

## 1. Matriz de compatibilidad verificada

Ejecutada el 2026-09-15 con Docker 29.7.2 en Linux: cada fila arranca la
imagen, siembra 3 filas con `isql`, respalda con el `gbak` **de la propia
imagen** (`BackupExecutor` + `databases[].gbak_path`) y restaura a una base
scratch con el mismo `gbak`, contando las filas.

| Firebird | Imagen (digest observado) | `gbak` de la familia | Charset probado | `.fbk` | Restore |
|---|---|---|---|---|---|
| 2.5.9 | `jacobalberty/firebird:2.5-sc` (`sha256:bc359ae5b0b3…`) | LI-V2.5.9.27139 | UTF8 (fijo de la imagen) | 2560 B | 3/3 filas |
| 3.0.9 | `firebirdsql/firebird:3.0.9` (`sha256:335490b2bc45…`) | LI-V3.0.9.33560 | WIN1252 | 1536 B | 3/3 filas |
| 4.0.5 | `firebirdsql/firebird:4.0.5` (`sha256:d9812f07291c…`) | LI-V4.0.5.3140 | ISO8859_1 | 1536 B | 3/3 filas |
| 5.0.4 | `firebirdsql/firebird:latest` (`sha256:1529560400fc…`) | LI-V5.0.4.1812 | UTF8 | 1536 B | 3/3 filas |
| 6.0 snapshot | `firebirdsql/firebird:6-snapshot` (`sha256:d73d741302b4…`) | LI-T6.0.0.2177 | UTF8 | 3584 B | 3/3 filas |

Evidencia: `uv run pytest tests/test_firebird_matrix.py -q -m integration -s`
→ **5 passed in 23.31 s** (0.14 s a 0.25 s de respaldo por fila; los tamaños
`.fbk` corresponden a bases mínimas de prueba). La fila 6.x es *best-effort*
(snapshot): se salta si la imagen no existe para la arquitectura del host o el
contenedor no arranca. La fila 4.0 se sumó por bajo costo (imagen oficial
disponible).

## 2. La regla de familia

`gbak` habla el protocolo del servidor y escribe un formato de respaldo
versionado; por eso ODIN no intenta puentear versiones:

1. **Misma versión mayor que la base.** La configuración recomendada (y la que
   prueba la suite) es un `gbak` de la familia del servidor.
2. **Un cliente 3+ no habla con un servidor 2.5 ni al revés.** Verificado en la
   red Docker de la matriz:
   - `gbak` 5.0 → servidor 2.5:
     `gbak: ERROR:invalid request BLR at offset 50 / data operation not supported`.
   - `gbak` 2.5 → servidor 5.0:
     `gbak: ERROR:connection rejected by remote interface`.
3. **Un `gbak` viejo no lee un respaldo nuevo.** `gbak` 2.5 restaurando un
   `.fbk` hecho por `gbak` 5.0: `gbak: ERROR:Expected backup version 1..9.
   Found 11`.
4. **Dentro de la familia moderna (3.0+) hay tolerancia hacia atrás.** En el
   smoke test, `gbak` 5.0 respaldó servidores 3.0/4.0 y restauró un `.fbk`
   hecho por `gbak` 2.5. Es un comportamiento observado, **no** el camino
   soportado por ODIN: no lo use como sustituto de la regla 1.

Consecuencia práctica: en un host con varias versiones instaladas, la
auto-detección elige **una** y no puede adivinar por base; fijá
`databases[].gbak_path` para cada familia.

## 3. `gbak_path`: auto-detección y override

Precedencia (implementada en `src/odin/backup.py`):

1. `databases[].gbak_path` explícito en el JSON.
2. `gbak_path` del ejecutor (`BackupExecutor`, uso programático).
3. Auto-detección de `src/odin/gbak_finder.py`, cacheada tras el primer uso.

Rutas que busca la auto-detección, en orden:

- **Windows** (`sys.platform == "win32"`):
  1. `C:\Program Files\Firebird\bin\gbak.exe`
  2. `C:\Program Files (x86)\Firebird\bin\gbak.exe`
  3. Subdirectorios versionados `Firebird*` / `firebird*` de ambas raíces
     (p. ej. `C:\Program Files (x86)\Firebird\Firebird_2_5\bin\gbak.exe`)
  4. Cada entrada de `PATH` + `gbak.exe`
- **Linux/POSIX**:
  1. `/usr/bin/gbak`
  2. `/usr/local/bin/gbak`
  3. `/opt/firebird/bin/gbak`, `/usr/lib/firebird/bin/gbak`,
     `/usr/local/firebird/bin/gbak` y sus subdirectorios versionados
     (`<raíz>/<versión>/bin/gbak`)
  4. Cada entrada de `PATH`

`/usr/local/firebird` es el prefijo por defecto de la instalación por tarball
(la familia 2.5 clásica) y se sumó a la búsqueda en el Item 070 al verificar la
matriz.

`odin validate` revisa el `gbak_path` de cada base:

| Situación | Severidad | Mensaje |
|---|---|---|
| `gbak_path: null` | INFO | "es null; se auto-detectará según SO y versión de Firebird" |
| Ruta de otro SO (p. ej. `C:\…` en Linux) | — | se omite con nota (OS-agnóstico) |
| Es un directorio | ERROR | "se esperaba el ejecutable gbak" |
| No existe | WARNING | "el respaldo de esta base fallará" |
| Existe pero no es ejecutable | WARNING | "no es ejecutable por el usuario actual" |
| Existe y es ejecutable | OK | "existe y es ejecutable" |

Ejemplos por plataforma:

```json
// Linux LTS
"databases": [
  {
    "name": "erp_principal",
    "connection": "localhost/3050:/var/lib/firebird/data/erp.fdb",
    "user": "SYSDBA",
    "password": "***",
    "charset": "ISO8859_1",
    "gbak_path": "/opt/firebird/bin/gbak"
  }
]
```

```json
// Windows Server (varias instalaciones: 2.5 y 5.0 conviviendo)
"databases": [
  {
    "name": "erp_principal",
    "connection": "localhost/3050:C:\\Datos\\ERP\\erp.fdb",
    "user": "SYSDBA",
    "password": "***",
    "charset": "ISO8859_1",
    "gbak_path": "C:\\Program Files (x86)\\Firebird\\Firebird_2_5\\bin\\gbak.exe"
  }
]
```

Opcionalmente, `databases[].gbak_timeout_sec` limita el respaldo de esa base
(default global `local.gbak_timeout_sec`, 7200 s).

## 4. Cadenas de conexión y charset

Formato de `databases[].connection`:

- Remota: `<host>[/<puerto>]:<ruta-o-alias>`; el puerto por defecto es 3050.
  - Linux: `localhost/3050:/var/lib/firebird/data/erp.fdb`
  - Windows: `localhost/3050:C:\Datos\ERP\erp.fdb`
  - Otro host: `firebird.interna/3050:/data/erp.fdb` (o el alias resuelto por
    el servidor: `firebird.interna:erp`).
- `gbak` corre donde corre ODIN; el `.fbk` se escribe en `local.work_dir` del
  host de ODIN.

**Charset:** `databases[].charset` se conserva en el JSON pero **no se pasa a
`gbak`** (no existe switch de charset; el respaldo transportable no depende
del charset de conexión). El charset real lo define la base al crearse en el
servidor; verificalo con
`SELECT rdb$character_set_name FROM rdb$database;`.

En la matriz ejecutada, el charset se controla al crear la base con las
convenciones de cada imagen:

| Imagen | Charset de creación |
|---|---|
| `jacobalberty/firebird:2.5-sc` | `DEFAULT CHARACTER SET UTF8` fijo (no configurable) |
| `firebirdsql/firebird:3.0.9` / `4.0.5` / `latest` / `6-snapshot` | `FIREBIRD_DATABASE_DEFAULT_CHARSET` (probados WIN1252, ISO8859_1 y UTF8) |

## 5. Incompatibilidades encontradas

- **Passwords de 2.5: 8 bytes significativos.** La autenticación legacy de
  2.5 limita la password; usá ≤ 8 caracteres para SYSDBA y usuarios (la matriz
  usa `matrixpw`). Un password más largo puede aceptarse en la creación y
  fallar al autenticar. Firebird 3+ usa SRP y admite passwords largas.
- **Variables de entorno de las imágenes Docker**: la familia 2.5 usa
  `ISC_PASSWORD`; la moderna, `FIREBIRD_ROOT_PASSWORD`. Además,
  `FIREBIRD_DATABASE` es un *nombre* en 2.5 (se crea en `/firebird/data`) y
  una *ruta* en la moderna (relativa a `/var/lib/firebird/data`).
- **Protocolo y formato de respaldo**: ver §2 (mensajes textuales incluidos).
- **Switches de `gbak`**: los nombres completos `-user`, `-password` y `-role`
  son los que usa ODIN porque las abreviaturas colisionan (`-u` es
  `-use_all_space`, `-p` es `-page_size`, `-r` es `-recreate_database`).
  `gbak` **no** tiene switch de charset. `-Z` (mayúscula) imprime la versión,
  pero en Firebird 5 sale con código 1 (solo como dato de diagnóstico).
- **Tipos de archivo**: ODIN respalda a `.fbk` y comprime a `.fbk.7z`; el
  restore a scratch de la matriz usa el mismo `gbak` con `-c`.
- **Firebird 6.x**: solo hay build *snapshot* (`firebirdsql/firebird:6-snapshot`,
  `LI-T6.0.0.2177`); funciona en la matriz, pero no es una versión estable para
  producción.

## 6. Reproducir la matriz localmente

Requisitos: Docker con daemon accesible. **No hace falta `gbak` en el host**:
el test invoca el binario de cada imagen con `docker exec` y monta el
`work_dir` en la misma ruta absoluta host↔contenedor.

```bash
docker pull jacobalberty/firebird:2.5-sc
docker pull firebirdsql/firebird:3.0.9
docker pull firebirdsql/firebird:4.0.5
docker pull firebirdsql/firebird:latest
docker pull firebirdsql/firebird:6-snapshot
uv run pytest tests/test_firebird_matrix.py -q -m integration -s
```

Cada fila imprime su evidencia (imagen, versión de `gbak`, charset, tamaño del
`.fbk` y filas restauradas). Sin Docker, los tests se **saltan** sin fallar.
Etiquetas/digests alternativos sin tocar el código:

| Fila | Variable | Default |
|---|---|---|
| 2.5 | `ODIN_FIREBIRD_25_IMAGE` | `jacobalberty/firebird:2.5-sc` |
| 3.0 | `ODIN_FIREBIRD_30_IMAGE` | `firebirdsql/firebird:3.0.9` |
| 4.0 | `ODIN_FIREBIRD_40_IMAGE` | `firebirdsql/firebird:4.0.5` |
| 5.0 | `ODIN_FIREBIRD_50_IMAGE` | `firebirdsql/firebird:latest` |
| 6.x | `ODIN_FIREBIRD_60_IMAGE` | `firebirdsql/firebird:6-snapshot` |
| Tests base | `ODIN_FIREBIRD_IMAGE` | `firebirdsql/firebird:latest` |

Las convenciones de las imágenes (variables, rutas de binarios/datos y helper
`FirebirdContainer`) están documentadas en `tests/firebird_container.py`.

## 7. Recomendación por tipo de despliegue

| Despliegue | Recomendación |
|---|---|
| Un solo Firebird por host | Auto-detección; aun así fijá `gbak_path` en el JSON de producción para no depender del `PATH` de la cuenta del servicio. |
| Varias versiones en el mismo host | `gbak_path` explícito **por base**; la auto-detección solo elige uno. |
| Windows Server con Firebird 2.5 | `C:\Program Files (x86)\Firebird\Firebird_2_5\bin\gbak.exe`; cuenta del servicio con permiso de ejecución. |
| Linux LTS con paquete del sistema | `/usr/lib/firebird/<mayor>/bin/gbak`; con tarball, `/opt/firebird/bin/gbak` o `/usr/local/firebird/bin/gbak`. |
| Servidor Firebird remoto | El `gbak` del host de ODIN debe ser de la misma familia que el servidor; no hace falta un servidor Firebird local. |
| Firebird 6.x | Válido para pruebas con snapshot; para producción, esperar una release estable y fijar la etiqueta/digest. |

---

## Enlaces

- Matriz ejecutable: `tests/test_firebird_matrix.py` (Item 069).
- Helper de contenedores: `tests/firebird_container.py`.
- Resolución del binario: `src/odin/gbak_finder.py` y `src/odin/backup.py`.
- Guía del modo residente y cuenta del servicio: [`docs/service.md`](service.md).
- Configuración y operación: [README](../README.md).
