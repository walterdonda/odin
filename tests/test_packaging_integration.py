"""Instalación limpia en Linux LTS dentro de un contenedor (Item 072).

El escenario instala el wheel construido por el repo en un `ubuntu:24.04`
limpio (sin el repositorio, sin el venv de desarrollo) usando el `uv` del host
copiado a un directorio de staging, y repite el ciclo documentado:
`uv tool install` → `odin --version` → `odin validate` → `odin service
status`; el escenario gated ``ODIN_CLEAN_CONTAINER_E2E=1`` suma el `odin run`
completo con la base Firebird 5.0 de la matriz, el sshd ephemeral y el
catcher SMTP de la suite.

Skip-safe: sin Docker, sin `uv` en el `PATH` o en un host no Linux los tests
se saltan con motivo. La instalación usa `UV_PYTHON_INSTALL_DIR` montado
read-only (el 3.14 gestionado del host) cuando existe, sin escribir en la
caché del host: la caché del contenedor es propia y efímera.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

from tests.firebird_container import (
    DOCKER,
    MATRIX_IMAGES,
    FirebirdContainer,
    FirebirdContainerError,
)
from tests.packaging_tools import (
    ROOT,
    Artifacts,
    PackagingToolError,
    build_artifacts,
    managed_python_dir,
)
from tests.smtp_catcher import SmtpCatcher, parse_message
from tests.sshd_ephemeral import EphemeralSshd

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(DOCKER is None, reason="Docker no instalado en el host"),
    pytest.mark.skipif(
        sys.platform != "linux", reason="capa de Linux LTS limpio (contenedor)"
    ),
]

UBUNTU_IMAGE = os.environ.get("ODIN_CLEAN_CONTAINER_IMAGE", "ubuntu:24.04")
CLEAN_USER = "odin_matrix"
CLEAN_PASSWORD = "matrixpw"
TABLE = "odin_matrix_rows"
ROW_COUNT = 3
SSHD_PASSWORD = "int-secreto"
SCRATCH_NAME = "odin_clean_restore.fdb"

SEED_SQL = f"""\
CREATE TABLE {TABLE} (id INTEGER NOT NULL PRIMARY KEY, note VARCHAR(40));
INSERT INTO {TABLE} (id, note) VALUES (1, 'fila uno');
INSERT INTO {TABLE} (id, note) VALUES (2, 'fila dos');
INSERT INTO {TABLE} (id, note) VALUES (3, 'fila tres');
COMMIT;
"""


def _staging_tools(tmp_path: Path) -> Path:
    """Copia `uv` y `docker` del host (binarios) al staging del contenedor."""
    staging = tmp_path / "tools"
    staging.mkdir()
    for name in ("uv", "docker"):
        source = shutil.which(name)
        if source is None:
            pytest.skip(f"{name} no está en el PATH del host")
        target = staging / name
        shutil.copy2(Path(source).resolve(), target)
        target.chmod(0o755)
    return staging


def _build_or_skip(tmp_path: Path) -> Artifacts:
    try:
        return build_artifacts(tmp_path / "dist")
    except PackagingToolError as exc:
        pytest.skip(str(exc))


def _install_lines(python_dir: Path | None) -> list[str]:
    lines = [
        "set -eu",
        "export PATH=/opt/odintools:$PATH",
        "export HOME=/tmp/odin-home",
        "export UV_TOOL_DIR=/tmp/odin-tools",
        "export UV_TOOL_BIN_DIR=/tmp/odin-bin",
        "export UV_CACHE_DIR=/tmp/uv-cache",
        "export UV_NO_PROGRESS=1",
        "mkdir -p $HOME $UV_TOOL_DIR $UV_TOOL_BIN_DIR $UV_CACHE_DIR",
    ]
    if python_dir is not None:
        lines += [
            "export UV_PYTHON_INSTALL_DIR=/opt/uv-python",
            "export UV_PYTHON_DOWNLOADS=manual",
        ]
    return lines


def _run_clean_container(
    *,
    script: str,
    wheel: Path,
    work_dir: Path,
    tools: Path,
    python_dir: Path | None,
    docker_socket: bool = False,
    mounts: Sequence[tuple[Path, str]] = (),
    timeout: float = 900.0,
) -> subprocess.CompletedProcess[str]:
    assert DOCKER is not None
    command = [DOCKER, "run", "--rm", "--network", "host"]
    if docker_socket:
        command += ["-v", "/var/run/docker.sock:/var/run/docker.sock"]
    command += [
        "-v",
        f"{tools}:/opt/odintools:ro",
        "-v",
        f"{wheel.parent}:/wheel:ro",
        "-v",
        f"{work_dir}:{work_dir}",
    ]
    if python_dir is not None:
        command += ["-v", f"{python_dir}:/opt/uv-python:ro"]
    for source, target in mounts:
        command += ["-v", f"{source}:{target}:ro"]
    command += [UBUNTU_IMAGE, "bash", "-c", script]
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout)


def _detail(completed: subprocess.CompletedProcess[str]) -> str:
    return (completed.stdout or "") + (completed.stderr or "")


def test_clean_linux_container_installs_and_runs_the_cli(tmp_path: Path) -> None:
    tools = _staging_tools(tmp_path)
    artifacts = _build_or_skip(tmp_path)
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    python_dir = managed_python_dir()
    script = "\n".join(
        [
            *_install_lines(python_dir),
            f"uv tool install --python 3.14 /wheel/{artifacts.wheel.name}",
            "$UV_TOOL_BIN_DIR/odin --version",
            "$UV_TOOL_BIN_DIR/odin validate --config /examples/config.linux.json",
            "$UV_TOOL_BIN_DIR/odin validate --config /examples/config.windows.json",
            "$UV_TOOL_BIN_DIR/odin service status --config /examples/config.linux.json",
            "echo CLEAN-OK",
        ]
    )
    completed = _run_clean_container(
        script=script,
        wheel=artifacts.wheel,
        work_dir=work_dir,
        tools=tools,
        python_dir=python_dir,
        mounts=[(ROOT / "examples", "/examples")],
    )
    assert completed.returncode == 0, _detail(completed)
    assert "odin 0.1.0" in completed.stdout
    assert "Configuración válida" in completed.stdout
    assert "Servicio del SO" in completed.stdout
    assert "CLEAN-OK" in completed.stdout


def test_clean_linux_container_odin_run_end_to_end(tmp_path: Path) -> None:
    if os.environ.get("ODIN_CLEAN_CONTAINER_E2E") != "1":
        pytest.skip(
            "end-to-end del contenedor gated (definir ODIN_CLEAN_CONTAINER_E2E=1)"
        )
    tools = _staging_tools(tmp_path)
    artifacts = _build_or_skip(tmp_path)
    python_dir = managed_python_dir()
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    remote_root = tmp_path / "remote"
    remote_root.mkdir()

    catcher = SmtpCatcher(host="0.0.0.0")
    sshd = EphemeralSshd(password=SSHD_PASSWORD, root=remote_root, host="0.0.0.0")
    container = FirebirdContainer(
        MATRIX_IMAGES["50"],
        mount=work_dir,
        user=CLEAN_USER,
        user_password=CLEAN_PASSWORD,
        charset="UTF8",
    )
    try:
        try:
            container.start()
            container.wait_ready()
        except (FirebirdContainerError, subprocess.TimeoutExpired) as exc:
            pytest.skip(f"imagen de la matriz no disponible: {exc}")
        container.isql(SEED_SQL, user=CLEAN_USER, password=CLEAN_PASSWORD)
        wrapper = container.gbak_wrapper(work_dir / "gbak-firebird")
        config_path = work_dir / "config.json"
        config_path.write_text(
            json.dumps(
                _build_config(work_dir, container, wrapper, sshd.port, catcher.port),
                indent=2,
            ),
            encoding="utf-8",
        )
        script = "\n".join(
            [
                *_install_lines(python_dir),
                f"uv tool install --python 3.14 /wheel/{artifacts.wheel.name}",
                "$UV_TOOL_BIN_DIR/odin --version",
                f"$UV_TOOL_BIN_DIR/odin run --config {config_path}",
                f"chown -R {os.getuid()}:{os.getgid()} {work_dir}",
                "echo E2E-OK",
            ]
        )
        completed = _run_clean_container(
            script=script,
            wheel=artifacts.wheel,
            work_dir=work_dir,
            tools=tools,
            python_dir=python_dir,
            docker_socket=True,
        )
        assert completed.returncode == 0, _detail(completed)
        assert "odin 0.1.0" in completed.stdout
        assert "E2E-OK" in completed.stdout

        backups = sorted(work_dir.glob("*.fbk"))
        archives = sorted(work_dir.glob("*.fbk.7z"))
        assert len(backups) == 1 and backups[0].stat().st_size > 0
        assert len(archives) == 1 and archives[0].stat().st_size > 0

        uploaded = remote_root / "backups" / "odin" / archives[0].name
        assert uploaded.is_file()
        assert uploaded.read_bytes() == archives[0].read_bytes()
        assert sshd.errors == []

        assert len(catcher.messages) == 1
        message = parse_message(catcher.messages[0])
        assert "ÉXITO" in str(message["Subject"])
        assert catcher.auth == [("odin-smtp", "smtp-secreto")]
        body = message.get_body(preferencelist=("plain",))
        assert body is not None
        assert "matrix50" in body.get_content()
        assert catcher.errors == []

        scratch = container.database_spec(SCRATCH_NAME)
        container.gbak(
            [
                "-c",
                str(backups[0]),
                scratch,
                "-user",
                "SYSDBA",
                "-password",
                container.root_password,
            ]
        )
        assert (
            container.count_rows(
                TABLE, database=scratch, user="SYSDBA", password=container.root_password
            )
            == ROW_COUNT
        )
    finally:
        container.remove()
        catcher.close()
        sshd.close()


def _build_config(
    work_dir: Path,
    container: FirebirdContainer,
    wrapper: Path,
    sshd_port: int,
    smtp_port: int,
) -> dict[str, object]:
    """Config JSON derivada del ejemplo de Linux para el escenario limpio."""
    config = json.loads(
        (ROOT / "examples" / "config.linux.json").read_text(encoding="utf-8")
    )
    config["databases"] = [
        {
            "name": "matrix50",
            "connection": container.database_spec(),
            "user": CLEAN_USER,
            "password": CLEAN_PASSWORD,
            "role": None,
            "charset": "UTF8",
            "gbak_path": str(wrapper),
        }
    ]
    config["compression"] = {"level": 7, "password": None}
    config["servers"] = [
        {
            "name": "sftp-clean",
            "host": "127.0.0.1",
            "port": sshd_port,
            "username": "odin",
            "auth": {"method": "password", "password": SSHD_PASSWORD},
            "remote_path": "/backups/odin",
            "host_key_policy": "accept-new",
        }
    ]
    config["notification"] = {
        "to": "control@example.com",
        "from": "odin-backups@example.com",
        "smtp": {
            "host": "127.0.0.1",
            "port": smtp_port,
            "starttls": False,
            "ssl": False,
            "username": "odin-smtp",
            "password": "smtp-secreto",
        },
    }
    config["local"] = {"work_dir": str(work_dir), "retention_days": 7}
    config["scheduler"] = {
        "enabled": False,
        "timezone": "America/Argentina/Buenos_Aires",
        "jobs": [],
    }
    return config
