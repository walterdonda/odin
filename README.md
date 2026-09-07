# ODIN

Respaldo externo de bases de datos Firebird (2.5 → 6): backup con `gbak`,
compresión 7z, transferencia SFTP (paramiko) y notificación por correo.

> Proyecto en desarrollo bajo el flujo AIDE (`docs/aide/`).

## Requisitos

- Python ≥ 3.14 (gestionado con [uv](https://docs.astral.sh/uv/))
- uv
- Firebird cliente o servidor instalado (aporta `gbak`)

## Quickstart (desarrollo)

```bash
uv sync              # instala dependencias y crea uv.lock
uv run pytest        # ejecuta la suite de tests
uv run odin --version
```

La documentación completa de instalación y operación llegará con el
Item 009 del roadmap.

## Validación de configuración

```bash
uv run odin validate --config ruta/al/config.json    # o vía ODIN_CONFIG
uv run odin validate --config ruta/al/config.json --strict
```

`odin validate` comprueba, en este orden:

1. **Estructura y tipos** del JSON (campos requeridos, rangos, enums, campos
   desconocidos con sugerencia de typo) y **semántica** (nombres únicos,
   jobs del scheduler que referencian bases existentes, coherencia entre
   `auth.method` y sus credenciales).
2. **Entorno local**: `local.work_dir` y `local.log_dir` (existentes, creables
   o en conflicto), `servers[].auth.private_key` con método `key` (existe, es
   legible, permisos recomendados `600`), `databases[].gbak_path` explícito
   (existe y es ejecutable), permisos del propio JSON, espacio libre vs.
   `local.min_free_mb`.
3. **Coherencia operativa**: scheduler habilitado sin jobs, bases no cubiertas
   por ningún job, ausencia de destinos SFTP, `host_key_policy: insecure`,
   `starttls: false`, retención desactivada.

La salida agrupa los hallazgos en `ERRORES`, `ADVERTENCIAS` y `VERIFICACIONES`,
cada uno con la ruta del campo implicado (p. ej. `config.servers[1].auth.private_key`).
Los errores y el veredicto de invalidez van a stderr; el contexto y el veredicto
de validez, a stdout.

### Exit codes

| Código | Significado |
|---|---|
| 0 | Configuración válida (puede tener advertencias) |
| 1 | Error interno inesperado |
| 2 | Error de configuración, de uso de la CLI, o advertencias con `--strict` |
| 3 / 4 | Reservados: fallo parcial / total del pipeline (Etapa 5) |

Con `--strict` las advertencias también devuelven 2: útil como gate previo al
despliegue o en CI.

### Garantías

- **Solo lectura:** `validate` no crea ni modifica archivos (el directorio de
  logs lo crea la configuración del logging, después de las verificaciones).
- **Sin red:** no comprueba conectividad SFTP, SMTP ni Firebird; un destino
  temporalmente caído no invalida la configuración.
- **Sin secretos:** la salida y el log nunca incluyen contraseñas,
  passphrases ni contenido de claves privadas.
- **OS-agnóstico:** una ruta cuyo sabor (Windows o POSIX) no coincide con el
  sistema donde se ejecuta no es comprobable: se omite con una nota, nunca
  cuenta como error.

