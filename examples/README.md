# Ejemplos de configuración de ODIN

Este directorio contiene configuraciones **de ejemplo**, listas para copiar y
adaptar. Reproducen el contrato OS-agnóstico de la visión del proyecto
(`docs/aide/vision.md` §5): el **mismo esquema** en ambas plataformas, solo
cambian los valores de rutas.

| Archivo | Plataforma | `connection` | `local.work_dir` |
|---|---|---|---|
| [`config.linux.json`](config.linux.json) | Linux LTS | `localhost/3050:/var/lib/firebird/data/erp.fdb` | `/var/backups/odin` |
| [`config.windows.json`](config.windows.json) | Windows Server | `localhost/3050:C:\\Datos\\ERP\\erp.fdb` | `D:\\Backups\\odin` |

> En JSON, las barras invertidas de Windows se escriben escapadas (`\\`).

## Uso

1. Copiá el ejemplo de tu plataforma a una ubicación **fuera** del repositorio
   (p. ej. `/etc/odin/config.json` o `C:\\ProgramData\\odin\\config.json`).
2. **Reemplazá todos los placeholder `***`** por las credenciales reales
   (contraseña de la base, contraseña SFTP del primer servidor y contraseña
   SMTP). El segundo servidor del ejemplo usa autenticación por **clave
   privada** (`~/.ssh/id_ed25519`): ajustá la ruta o cambiá a `method:
   "password"` si preferís.
3. Ajustá hosts, puertos, rutas remotas, casillas de correo, horarios del
   scheduler y zona horaria a tu entorno.
4. Validá la configuración antes de ejecutar:

   ```bash
   odin validate --config /ruta/al/config.json
   ```

## Seguridad (importante)

El JSON contiene **credenciales en texto legible** (decisión explícita del
proyecto). Por eso:

- **Restringí los permisos** del archivo: `chmod 600 config.json` en Linux;
  en Windows, ajustá las ACL para que solo la cuenta de servicio lo lea.
- **No lo commitees** al control de versiones: excluí el JSON real (los
  ejemplos de este directorio sí se versionan, con secretos `***`).
- `odin validate` **avisa** si el archivo tiene permisos abiertos (p. ej. 644)
  y nunca imprime contraseñas, passphrases ni contenido de claves.

## Validación y exit codes

```bash
odin validate --config /ruta/al/config.json           # válida → 0
odin validate --config /ruta/al/config.json --strict  # advertencias → 2
```

| Código | Significado |
|---|---|
| 0 | Configuración válida (puede tener advertencias) · `odin run`: todas las bases completaron respaldo, compresión y transferencia **y** el correo se envió |
| 1 | Error interno inesperado · `odin run`: el correo no se pudo enviar en una corrida por lo demás exitosa |
| 2 | Error de configuración, de uso de la CLI, o advertencias con `--strict` |
| 3 | `odin run`: fallo parcial (algunas bases completaron todas las fases y otras fallaron en alguna); el desenlace del correo no cambia este código |
| 4 | `odin run`: fallo total (ninguna base completó todas las fases) o lote no ejecutado/vacío; tiene precedencia sobre el correo |

Tal como se commitean, los ejemplos devuelven **0** en Linux con un par de
advertencias esperables y no bloqueantes (permisos 644 del archivo y
`work_dir` de desarrollo no creable sin root). Con `--strict` devuelven **2**
por esas mismas advertencias: están pensados como plantilla, no para pasar
`--strict` sin editar.

Una vez adaptados, `odin run --config /ruta/al/config.json` ejecuta el ciclo
completo (respaldo → compresión → transferencia SFTP → correo → retención
local): ver [`README.md`](../README.md#ejecución-de-respaldos-odin-run),
[Notificación por correo](../README.md#notificación-por-correo) y
[Retención local](../README.md#retención-local).

## Campos opcionales (no mostrados en los ejemplos)

Los ejemplos mantienen la estructura mínima de la visión. El modelo de
configuración acepta además estos campos **opcionales** de
confiabilidad/observabilidad, con sus valores por defecto:

| Sección | Campo | Default | Descripción |
|---|---|---|---|
| `databases[]` | `gbak_timeout_sec` | `null` | Timeout por base; si es `null`, usa `local.gbak_timeout_sec`. |
| `servers[]` | `host_key_policy` | `"strict"` | Política de host keys SSH: `strict`, `known_hosts`, `accept-new`, `insecure`. |
| `notification` | `log_tail_lines` | `50` | Líneas finales del log adjuntas al correo de ejecución. |
| `notification.smtp` | `ssl` | `false` | SSL implícito (típicamente puerto 465); exige `starttls: false`. |
| `local` | `log_level` | `"INFO"` | Nivel de logging: `DEBUG`, `INFO`, `WARNING`, `ERROR`. |
| `local` | `log_dir` | `null` | Directorio de logs; si es `null`, se usa `<work_dir>/logs`. |
| `local` | `min_free_mb` | `1024` | Espacio libre mínimo exigido en `work_dir` antes de respaldar. |
| `local` | `gbak_timeout_sec` | `7200` | Timeout global de `gbak` (segundos). |
| `local` | `sftp_retries` | `3` | Reintentos de transferencia SFTP ante fallos transitorios. |
| `local` | `sftp_connect_timeout_sec` | `30` | Timeout de conexión SFTP (segundos). |

`compression.password` (mostrado como `null`) habilita el cifrado **AES-256**
del `.7z` cuando se le asigna un valor (Etapa 3).

> Estos campos se consumen en las etapas implementadas: `odin run` usa respaldo,
> compresión, transferencia, correo (Etapa 5) y retención local, y `odin
> validate` verifica tipo/rango de todos —incluidos los del scheduler (Etapa 6,
> aún sin ejecutor)—. El `charset` se conserva en el contrato pero no se pasa a
> `gbak` (no tiene switch de charset; el respaldo transportable no depende del
> charset de conexión).
