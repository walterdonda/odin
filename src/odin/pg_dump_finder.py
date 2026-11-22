"""Auto-detección del binario ``pg_dump`` según SO y versión de PostgreSQL (ticket 03).

Busca primero en las rutas típicas del sistema operativo actual (las
instalaciones versionadas de PostgreSQL de §2.6 de ``docs/postgresql.md``) y
después en el ``PATH``. Regla de versión (§2.5): entre las rutas versionadas
—el major está codificado en la ruta— solo se aceptan majors ≥ 18 y gana el
mayor; si hay instalaciones versionadas y ninguna llega a 18, devuelve
``None`` (equivale a "binario no encontrado", con el hint del engine). Las
rutas sin versión en el nombre (``/usr/bin/pg_dump``, ``/usr/local/pgsql/bin``
y las entradas del ``PATH``) se prueban únicamente si no hay ninguna
instalación versionada: para ellas basta la existencia (sin verificación de
versión en runtime, regla documentada en §2.5).

El override explícito ``databases[].pg_dump_path`` de la configuración tiene
precedencia sobre esta detección (lo resuelve ``odin.backup``).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_MIN_MAJOR = 18

_WINDOWS_VERSIONED_ROOT = Path("C:/Program Files/PostgreSQL")

_POSIX_DEBIAN_VERSIONED_ROOT = Path("/usr/lib/postgresql")
_POSIX_PGDG_GLOB = "pgsql-*"

_POSIX_UNVERSIONED = (
    Path("/usr/bin/pg_dump"),  # wrapper de Debian/Ubuntu y ruta de Fedora
    Path("/usr/local/pgsql/bin/pg_dump"),  # instalación desde fuente
)


def _as_major(name: str) -> int | None:
    """Major de PostgreSQL codificado en el nombre de una carpeta, o ``None``."""
    try:
        return int(name)
    except ValueError:
        return None


def _windows_candidates() -> list[tuple[int, Path]]:
    """Instalaciones versionadas de Windows: (major, ``pg_dump.exe``).

    Forma de §2.6: ``C:\\Program Files\\PostgreSQL\\<major>\\bin\\pg_dump.exe``.
    """
    candidates: list[tuple[int, Path]] = []
    for versioned in sorted(_WINDOWS_VERSIONED_ROOT.glob("*")):
        major = _as_major(versioned.name)
        if major is not None:
            candidates.append((major, versioned / "bin" / "pg_dump.exe"))
    return candidates


def _posix_versioned_candidates() -> list[tuple[int, Path]]:
    """Instalaciones versionadas de Linux/POSIX: (major, ``pg_dump``).

    Debian/Ubuntu (``/usr/lib/postgresql/<major>/bin/pg_dump``) y PGDG yum
    (``/usr/pgsql-<major>/bin/pg_dump``).
    """
    candidates: list[tuple[int, Path]] = []
    for versioned in sorted(_POSIX_DEBIAN_VERSIONED_ROOT.glob("*")):
        major = _as_major(versioned.name)
        if major is not None:
            candidates.append((major, versioned / "bin" / "pg_dump"))
    for pgsql_dir in sorted(Path("/usr").glob(_POSIX_PGDG_GLOB)):
        major = _as_major(pgsql_dir.name.removeprefix("pgsql-"))
        if major is not None:
            candidates.append((major, pgsql_dir / "bin" / "pg_dump"))
    return candidates


def _path_candidates(executable: str) -> list[Path]:
    """Cada entrada de ``PATH`` + el nombre del ejecutable."""
    candidates: list[Path] = []
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if entry:
            candidates.append(Path(entry) / executable)
    return candidates


def find_pg_dump() -> Path | None:
    """Devuelve la ruta a ``pg_dump`` 18+ si se encuentra en el sistema, o ``None``.

    La comprobación es de existencia, no de ejecutabilidad: la validación fina
    de permisos la hace ``odin validate`` (``validate._check_pg_dump_paths``).
    La versión se lee de la ruta típica (nunca se ejecuta ``pg_dump --version``
    en runtime): las rutas sin versión en el nombre solo se aceptan cuando no
    hay ninguna instalación versionada descubierta.
    """
    windows = sys.platform == "win32"
    executable = "pg_dump.exe" if windows else "pg_dump"
    versioned = _windows_candidates() if windows else _posix_versioned_candidates()
    existing = [(major, path) for major, path in versioned if path.exists()]
    if existing:
        eligible = sorted((major, path) for major, path in existing if major >= _MIN_MAJOR)
        if not eligible:
            return None
        # orden creciente de (major, ruta): el último es el major mayor
        return eligible[-1][1]
    unversioned = ([] if windows else list(_POSIX_UNVERSIONED)) + _path_candidates(executable)
    for candidate in unversioned:
        if candidate.exists():
            return candidate
    return None
