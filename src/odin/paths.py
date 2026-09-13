"""Normalización OS-agnóstica de rutas de configuración de ODIN (Item 003).

Acepta los separadores ``/`` y ``\\`` indistintamente, expande ``~`` y
``~usuario`` con independencia del separador usado, y resuelve rutas
relativas contra un directorio base (la ubicación del JSON de
configuración en ``odin.config``).

Solo stdlib (``pathlib``, ``re``, ``os``). No se usa
``PurePath.expanduser`` porque no existe para rutas puras en Python 3.14.

Notas de comportamiento:

- La absolutitud se juzga por el *sabor* de la ruta (Windows o POSIX),
  no por el SO actual: ``D:\\...`` no se resuelve contra el directorio
  del JSON aunque se parsee en Linux.
- ``..`` no se colapsa léxicamente (pathlib lo preserva).
- En Linux un ``\\`` literal dentro de un nombre de archivo se
  interpreta como separador: trade-off aceptado del contrato
  OS-agnóstico de la configuración.
"""

from __future__ import annotations

import os
import re
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath

__all__ = ["expand_user", "is_windows_flavor", "normalize_path", "resolve_path"]

_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def is_windows_flavor(raw: str) -> bool:
    """True si la cadena tiene sabor Windows (``\\`` o letra de unidad).

    El prefijo UNC con barras ``//srv/share`` no se trata como Windows:
    su forma canónica coincide con la POSIX y ambas lo consideran
    absoluto.
    """
    return "\\" in raw or _DRIVE_RE.match(raw) is not None


def expand_user(raw: str) -> str:
    """Expande el segmento inicial ``~`` o ``~usuario`` con cualquier separador.

    ``~`` resuelve a ``Path.home()``; ``~usuario`` delega en
    ``os.path.expanduser`` (en Windows ntpath no resuelve ``~usuario``
    y el segmento se conserva sin cambios). Si el usuario no existe
    (POSIX), el segmento también se conserva.
    """
    if not raw.startswith("~"):
        return raw
    end = 1
    while end < len(raw) and raw[end] not in "/\\":
        end += 1
    segment, rest = raw[:end], raw[end:]
    if segment == "~":
        return str(Path.home()) + rest
    return os.path.expanduser(segment) + rest


def normalize_path(raw: str, *, base_dir: Path | str | None = None) -> Path:
    """Normaliza una ruta de configuración para el SO actual.

    Aplica, en orden: strip, expansión de ``~``, normalización de
    separadores ``/`` y ``\\`` (vía ``PureWindowsPath``/``PurePosixPath``
    según el sabor) y resolución contra ``base_dir`` si la ruta es
    relativa. Con ``base_dir=None`` las rutas relativas se devuelven
    como están.

    Lanza ``ValueError`` si ``raw`` es vacía o solo whitespace.
    """
    value = expand_user(raw.strip())
    if not value:
        raise ValueError("la ruta de configuración no debe ser vacía")
    pure: PurePath = PureWindowsPath(value) if is_windows_flavor(value) else PurePosixPath(value)
    canonical = pure.as_posix()
    if pure.is_absolute() or base_dir is None:
        return Path(canonical)
    return Path(base_dir) / canonical


def resolve_path(raw: str, base_dir: Path | str | None = None) -> Path:
    """Resuelve una ruta de forma definitiva utilizando la lógica de normalización.
    """
    return normalize_path(raw, base_dir=base_dir)

