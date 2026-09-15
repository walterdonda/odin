"""Auto-detección del binario ``gbak`` según SO y versión de Firebird (Item 011).

Busca primero en las rutas típicas del sistema operativo actual (incluidas las
instalaciones versionadas de Firebird) y después en el ``PATH``. El override
explícito ``databases[].gbak_path`` de la configuración tiene precedencia sobre
esta detección (lo resuelve ``odin.backup``).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_WINDOWS_ROOTS = (
    Path("C:/Program Files/Firebird"),
    Path("C:/Program Files (x86)/Firebird"),
)

_POSIX_ROOTS = (
    Path("/opt/firebird"),
    Path("/usr/lib/firebird"),
    Path("/usr/local/firebird"),
)

_VERSION_GLOBS = ("Firebird*", "firebird*")


def _windows_candidates() -> list[Path]:
    """Rutas típicas de ``gbak.exe`` en Windows, versionadas incluidas."""
    candidates: list[Path] = []
    for root in _WINDOWS_ROOTS:
        candidates.append(root / "bin" / "gbak.exe")
        if root.is_dir():
            for pattern in _VERSION_GLOBS:
                for versioned in sorted(root.glob(pattern)):
                    candidates.append(versioned / "bin" / "gbak.exe")
    return candidates


def _posix_candidates() -> list[Path]:
    """Rutas típicas de ``gbak`` en Linux/POSIX, versionadas incluidas."""
    candidates = [Path("/usr/bin/gbak"), Path("/usr/local/bin/gbak")]
    for root in _POSIX_ROOTS:
        candidates.append(root / "bin" / "gbak")
        if root.is_dir():
            for versioned in sorted(root.glob("*")):
                candidates.append(versioned / "bin" / "gbak")
    return candidates


def _path_candidates(executable: str) -> list[Path]:
    candidates: list[Path] = []
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if entry:
            candidates.append(Path(entry) / executable)
    return candidates


def find_gbak() -> Path | None:
    """Devuelve la ruta a ``gbak`` si se encuentra en el sistema, o ``None``.

    La comprobación es de existencia, no de ejecutabilidad: la validación fina
    de permisos la hace ``odin validate`` (``validate._check_gbak_paths``).
    """
    windows = sys.platform == "win32"
    executable = "gbak.exe" if windows else "gbak"
    candidates = (_windows_candidates() if windows else _posix_candidates()) + _path_candidates(
        executable
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None
