"""Helpers de empaquetado reutilizables por los tests del Item 072.

`build_artifacts` corre ``uv build --out-dir`` una sola vez y devuelve las
rutas del wheel y del sdist; `clean_tool_env` prepara un entorno aislado
(``HOME``/``UV_TOOL_DIR``/``UV_TOOL_BIN_DIR`` temporales) para verificar
``uv tool install`` sin tocar el venv del repo.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

UV = shutil.which("uv")

BUILD_TIMEOUT_SEC = 600.0


class PackagingToolError(RuntimeError):
    """Fallo al construir o inspeccionar los artefactos de empaquetado."""


@dataclass(frozen=True, slots=True)
class Artifacts:
    """Rutas del wheel y el sdist producidos por ``uv build``."""

    wheel: Path
    sdist: Path


def uv_binary() -> str:
    """Ruta de ``uv`` (error claro si el host no lo tiene)."""
    if UV is None:
        raise PackagingToolError("uv no está instalado en el host")
    return UV


def build_artifacts(out_dir: Path, *, timeout: float = BUILD_TIMEOUT_SEC) -> Artifacts:
    """Corre ``uv build --out-dir`` y devuelve wheel + sdist."""
    out_dir.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [uv_binary(), "build", "--out-dir", str(out_dir)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise PackagingToolError(
            f"uv build falló (código {completed.returncode}): "
            f"{(completed.stderr or completed.stdout).strip()}"
        )
    wheels = sorted(out_dir.glob("*.whl"))
    sdists = sorted(out_dir.glob("*.tar.gz"))
    if not wheels or not sdists:
        raise PackagingToolError(f"uv build no produjo wheel y sdist en {out_dir}")
    return Artifacts(wheel=wheels[0], sdist=sdists[0])


def existing_uv_cache() -> Path | None:
    """Caché de uv del host, para no re-descargar dependencias en el test."""
    configured = os.environ.get("UV_CACHE_DIR")
    if configured:
        return Path(configured)
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        candidate = Path(local) / "uv" / "cache" if local else None
    else:
        candidate = Path.home() / ".cache" / "uv"
    return candidate if candidate is not None and candidate.is_dir() else None


def managed_python_dir() -> Path | None:
    """Intérpretes gestionados por uv del host, si incluyen un 3.14.

    Los tests de contenedor montan este directorio read-only y usan
    ``--python 3.14`` para evitar la descarga del intérprete sin escribir en
    la caché del host (el caché del contenedor es propio y efímero).
    """
    configured = os.environ.get("UV_PYTHON_INSTALL_DIR")
    base = (
        Path(configured)
        if configured
        else Path.home() / ".local" / "share" / "uv" / "python"
    )
    if not base.is_dir() or not any(base.glob("cpython-3.14*")):
        return None
    return base


def clean_tool_env(base: Path) -> dict[str, str]:
    """Entorno aislado para ``uv tool install``.

    ``HOME`` (``USERPROFILE`` en Windows), ``UV_TOOL_DIR`` y
    ``UV_TOOL_BIN_DIR`` apuntan a directorios nuevos bajo ``base``: el tool
    queda fuera del venv del repo y de cualquier instalación previa. La caché
    de descargas se comparte con el host cuando existe (es solo caché, no
    afecta el aislamiento de lo instalado).
    """
    home = base / "home"
    tools = base / "tools"
    bin_dir = base / "bin"
    for path in (home, tools, bin_dir):
        path.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "UV_TOOL_DIR": str(tools),
            "UV_TOOL_BIN_DIR": str(bin_dir),
            "UV_NO_PROGRESS": "1",
        }
    )
    if os.name == "nt":
        env["USERPROFILE"] = str(home)
    cache = existing_uv_cache()
    if cache is not None:
        env["UV_CACHE_DIR"] = str(cache)
    return env


def tool_executable(env: dict[str, str]) -> Path:
    """Ruta del ejecutable ``odin`` instalado con ``uv tool install``."""
    bin_dir = Path(env["UV_TOOL_BIN_DIR"])
    name = "odin.exe" if os.name == "nt" else "odin"
    return bin_dir / name
