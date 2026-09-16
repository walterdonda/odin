"""Tests de empaquetado y de instalación limpia en host (Item 072).

La metadata del `pyproject.toml` se verifica siempre (sin build). El build
real (`uv build`), el contenido del wheel/sdist y la instalación con
`uv tool install` en un entorno aislado quedan **gated** por
``ODIN_BUILD_ARTIFACTS=1`` por ser lentos y necesitar red/caché de uv.
"""

from __future__ import annotations

import os
import subprocess
import tarfile
import tomllib
import zipfile
from pathlib import Path

import pytest

from odin import __version__ as ODIN_VERSION
from tests.packaging_tools import (
    ROOT,
    Artifacts,
    PackagingToolError,
    build_artifacts,
    clean_tool_env,
    tool_executable,
    uv_binary,
)

PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

BUILD_ENABLED = os.environ.get("ODIN_BUILD_ARTIFACTS") == "1"


def test_project_metadata_declares_python_and_entry_point() -> None:
    assert PROJECT["name"] == "odin"
    assert PROJECT["version"] == ODIN_VERSION
    assert PROJECT["requires-python"] == ">=3.14"
    assert PROJECT["scripts"]["odin"] == "odin.cli:main"


@pytest.fixture(scope="module")
def artifacts(tmp_path_factory: pytest.TempPathFactory) -> Artifacts:
    if not BUILD_ENABLED:
        pytest.skip("build de artefactos omitido (definir ODIN_BUILD_ARTIFACTS=1)")
    try:
        return build_artifacts(tmp_path_factory.mktemp("dist"))
    except PackagingToolError as exc:
        pytest.skip(str(exc))


def test_wheel_contains_package_entry_point_and_metadata(artifacts: Artifacts) -> None:
    with zipfile.ZipFile(artifacts.wheel) as archive:
        names = archive.namelist()
        assert "odin/__init__.py" in names
        assert "odin/cli.py" in names
        assert any(name.startswith("odin/service/") for name in names)
        assert not any(name.startswith("tests/") for name in names)

        dist_info = next(
            name.split("/")[0] for name in names if name.endswith(".dist-info/METADATA")
        )
        entry_points = archive.read(f"{dist_info}/entry_points.txt").decode("utf-8")
        assert "[console_scripts]" in entry_points
        assert "odin = odin.cli:main" in entry_points

        metadata = archive.read(f"{dist_info}/METADATA").decode("utf-8")
        assert "Requires-Python: >=3.14" in metadata
        assert "Requires-Dist: paramiko" in metadata
        assert "Requires-Dist: py7zr" in metadata
        assert "Requires-Dist: apscheduler" in metadata
        assert "Requires-Dist: tzdata" in metadata
        assert "Requires-Dist: pytest" not in metadata


def test_sdist_contains_project_sources(artifacts: Artifacts) -> None:
    with tarfile.open(artifacts.sdist) as archive:
        names = archive.getnames()
    assert any(name.endswith("src/odin/cli.py") for name in names)
    assert any(name.endswith("pyproject.toml") for name in names)
    assert any(name.endswith("README.md") for name in names)


def test_clean_uv_tool_install_runs_the_cli(artifacts: Artifacts, tmp_path: Path) -> None:
    env = clean_tool_env(tmp_path / "isolated")
    install = subprocess.run(
        [uv_binary(), "tool", "install", str(artifacts.wheel)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert install.returncode == 0, install.stderr
    odin = tool_executable(env)
    assert odin.is_file()

    version = subprocess.run(
        [str(odin), "--version"], env=env, capture_output=True, text=True, timeout=120
    )
    assert version.returncode == 0
    assert version.stdout.strip() == f"odin {ODIN_VERSION}"

    for example in ("config.linux.json", "config.windows.json"):
        validated = subprocess.run(
            [
                str(odin),
                "validate",
                "--config",
                str(ROOT / "examples" / example),
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert validated.returncode == 0, validated.stdout + validated.stderr

    status = subprocess.run(
        [
            str(odin),
            "service",
            "status",
            "--config",
            str(ROOT / "examples" / "config.linux.json"),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert status.returncode == 0
    assert "Servicio del SO" in status.stdout
