# Ejemplos de configuración de ODIN

Este directorio contiene configuraciones **de ejemplo**, listas para copiar y
adaptar. Reproducen el contrato OS-agnóstico de la visión del proyecto
(`docs/aide/vision.md` §5): el **mismo esquema** en ambas plataformas, solo
cambian los valores de rutas.

| Archivo | Plataforma | Bases | `local.work_dir` |
|---|---|---|---|
| [`config.linux.json`](config.linux.json) | Linux LTS | Firebird (`nombre_clave_sistema`) + PostgreSQL (`ventas_pg`) | `/var/backups/odin` |
| [`config.windows.json`](config.windows.json) | Windows Server | Firebird (`nombre_clave_sistema`) + PostgreSQL (`ventas_pg`) | `D:\\Backups\\odin` |

Cada ejemplo trae **una entrada por motor**: el campo `databases[].type`
(`"firebird"` | `"postgresql"`, obligatorio) elige el motor y qué campos
aplican —en Firebird, `connection`; en PostgreSQL, `host`, `port`, `dbname`—.
El resto del pipeline (compresión, SFTP, correo, retención, scheduler) es el
mismo para ambos. El modelo multi-motor está explicado en
[`docs/engines.md`](../docs/engines.md) y la referencia completa de todos los
campos —tipo, obligatoriedad, default, rangos, reglas cruzadas y límites de la
versión— en [`docs/configuration.md`](../docs/configuration.md).

> En JSON, las barras invertidas de Windows se escriben escapadas (`\\`).

## Uso

1. Copiá el ejemplo de tu plataforma a una ubicación **fuera** del repositorio
   (p. ej. `/etc/odin/config.json` o `C:\\ProgramData\\odin\\config.json`).
2. **Reemplazá todos los placeholder `***`** por las credenciales reales
   (contraseñas de las bases, contraseña SFTP del primer servidor y contraseña
   SMTP). El segundo servidor del ejemplo usa autenticación por **clave
   privada RSA** (`~/.ssh/id_rsa`): ajustá la ruta o cambiá a `method:
   "password"` si preferís. Recordá que ODIN solo acepta claves **RSA** en
   formato OpenSSH/PEM (las Ed25519 no están soportadas todavía; ver
   [`docs/security.md`](../docs/security.md#3-autenticación-sftp-clave-privada-frente-a-contraseña)).
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

Tal como se commitean, los ejemplos devuelven **0** en Linux con un par de
advertencias esperables y no bloqueantes (permisos 644 del archivo y
`work_dir` de desarrollo no creable sin root). Con `--strict` devuelven **2**
por esas mismas advertencias: están pensados como plantilla, no para pasar
`--strict` sin editar.

La tabla completa de exit codes está en el
[`README.md`](../README.md#comandos).

Una vez adaptados, `odin run --config /ruta/al/config.json` ejecuta el ciclo
completo (respaldo del motor de cada base → compresión → transferencia SFTP →
correo → retención local): ver [Operación](../README.md#operación) en el
README.

## Campos opcionales

Los ejemplos muestran la estructura mínima; el modelo acepta además campos
opcionales por base (`gbak_path`, `pg_dump_path`, `gbak_timeout_sec`,
`pg_dump_timeout_sec`, `role`, `charset`) y por bloque (políticas de host key,
reintentos SFTP, `log_dir`, `min_free_mb`, …), todos con sus defaults y reglas
en [`docs/configuration.md`](../docs/configuration.md).

`compression.password` (mostrado como `null`) habilita el cifrado **AES-256**
del artefacto comprimido cuando se le asigna un valor.

> Los campos marcados *aceptado sin efecto* en
> [`docs/configuration.md`](../docs/configuration.md) se validan al cargar
> pero la versión actual todavía no los aplica; el detalle de cada límite está
> en su [§11](../docs/configuration.md#11-notas-de-implementación-y-límites-conocidos).
