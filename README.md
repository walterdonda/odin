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
