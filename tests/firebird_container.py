"""Helper de contenedores Firebird para los tests de integración (Item 069).

Arranca contenedores de las imágenes de Firebird por familia y expone lo
necesario para un flujo de respaldo/restauración real **sin requerir ``gbak``
en el host**: el binario que se usa es el de la propia imagen, invocado con
``docker exec`` a través de un wrapper (``FirebirdContainer.gbak_wrapper``).
El ``work_dir`` se monta en la misma ruta absoluta host↔contenedor para que
las rutas que ``BackupExecutor`` pasa al wrapper sean válidas en ambos lados.

Familias y convenciones de entorno:

- **legacy (Firebird 2.5)**: ``ISC_PASSWORD`` (password de SYSDBA),
  ``FIREBIRD_DATABASE`` como *nombre* (la imagen crea la base en
  ``/firebird/data/<nombre>``), ``FIREBIRD_USER``/``FIREBIRD_PASSWORD``
  opcionales; binarios en ``/usr/local/firebird/bin``. La imagen crea la base
  con ``DEFAULT CHARACTER SET UTF8`` fijo (no admite charset configurable).
- **moderna (Firebird 3.0+ / 5.0 / 6.0)**: ``FIREBIRD_ROOT_PASSWORD``,
  ``FIREBIRD_DATABASE`` como ruta (relativa a ``/var/lib/firebird/data``),
  ``FIREBIRD_DATABASE_DEFAULT_CHARSET`` y
  ``FIREBIRD_USER``/``FIREBIRD_PASSWORD``; binarios en ``/opt/firebird/bin``.

Imágenes de la matriz (digests de imagen observados el 2026-09-15 con Docker
29.7.2; los tags pueden moverse y los overrides por entorno permiten fijarlos):

- ``jacobalberty/firebird:2.5-sc`` — ``sha256:bc359ae5b0b3…`` (gbak 2.5.9).
- ``firebirdsql/firebird:3.0.9`` — ``sha256:335490b2bc45…`` (gbak 3.0.9).
- ``firebirdsql/firebird:4.0.5`` — ``sha256:d9812f07291c…`` (gbak 4.0.5).
- ``firebirdsql/firebird:latest`` — 5.0.4, ``sha256:1529560400fc…`` (gbak 5.0.4).
- ``firebirdsql/firebird:6-snapshot`` — ``sha256:d73d741302b4…`` (gbak 6.0.0).

Variables de entorno (opcionales):

- ``ODIN_FIREBIRD_25_IMAGE``, ``ODIN_FIREBIRD_30_IMAGE``,
  ``ODIN_FIREBIRD_40_IMAGE``, ``ODIN_FIREBIRD_50_IMAGE`` y
  ``ODIN_FIREBIRD_60_IMAGE``: override por fila de la matriz
  (``MATRIX_IMAGES``).
- ``ODIN_FIREBIRD_IMAGE``: imagen de la familia moderna por defecto para
  ``tests/test_backup_integration.py`` y ``tests/test_notify_integration.py``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

DOCKER = shutil.which("docker")

DEFAULT_ROOT_PASSWORD = "masterkey"
DEFAULT_DATABASE_NAME = "odin_matrix.fdb"
DEFAULT_READY_TIMEOUT_SEC = 60.0

LEGACY_BIN_DIR = "/usr/local/firebird/bin"
LEGACY_DATA_DIR = "/firebird/data"
MODERN_BIN_DIR = "/opt/firebird/bin"
MODERN_DATA_DIR = "/var/lib/firebird/data"


class FirebirdContainerError(RuntimeError):
    """Fallo al preparar o ejercitar un contenedor Firebird de integración."""


def _env_image(variable: str, default: str) -> str:
    return os.environ.get(variable) or default


@dataclass(frozen=True, slots=True)
class FirebirdImage:
    """Imagen Docker de Firebird y las convenciones de su familia."""

    key: str
    image: str
    major: int
    bin_dir: str
    data_dir: str

    @property
    def legacy(self) -> bool:
        """Firebird 2.5 usa las variables de entorno y rutas de la familia legacy."""
        return self.major < 3

    @property
    def gbak(self) -> str:
        return f"{self.bin_dir}/gbak"

    @property
    def isql(self) -> str:
        return f"{self.bin_dir}/isql"

    def database_path(self, name: str = DEFAULT_DATABASE_NAME) -> str:
        return f"{self.data_dir}/{name}"

    def database_spec(self, name: str = DEFAULT_DATABASE_NAME) -> str:
        """Especificación de conexión válida *dentro* del propio contenedor."""
        return f"localhost/3050:{self.database_path(name)}"

    def environment(
        self,
        *,
        root_password: str,
        database_name: str | None = None,
        user: str | None = None,
        user_password: str | None = None,
        charset: str | None = None,
    ) -> dict[str, str]:
        """Variables de entorno de arranque de la imagen."""
        if charset is not None and self.legacy:
            raise ValueError(
                "la familia 2.5 crea la base con DEFAULT CHARACTER SET UTF8 fijo"
            )
        env: dict[str, str] = {
            "ISC_PASSWORD" if self.legacy else "FIREBIRD_ROOT_PASSWORD": root_password
        }
        if database_name is not None:
            env["FIREBIRD_DATABASE"] = (
                database_name if self.legacy else self.database_path(database_name)
            )
        if user is not None:
            if user_password is None:
                raise ValueError("FIREBIRD_USER requiere FIREBIRD_PASSWORD")
            env["FIREBIRD_USER"] = user
            env["FIREBIRD_PASSWORD"] = user_password
        if charset is not None:
            env["FIREBIRD_DATABASE_DEFAULT_CHARSET"] = charset
        return env


def modern_image(image: str | None = None) -> FirebirdImage:
    """Imagen de la familia moderna (3.0+), con override ``ODIN_FIREBIRD_IMAGE``."""
    return FirebirdImage(
        key="modern",
        image=image or _env_image("ODIN_FIREBIRD_IMAGE", "firebirdsql/firebird:latest"),
        major=5,
        bin_dir=MODERN_BIN_DIR,
        data_dir=MODERN_DATA_DIR,
    )


MATRIX_IMAGES: Mapping[str, FirebirdImage] = {
    "25": FirebirdImage(
        key="25",
        image=_env_image("ODIN_FIREBIRD_25_IMAGE", "jacobalberty/firebird:2.5-sc"),
        major=2,
        bin_dir=LEGACY_BIN_DIR,
        data_dir=LEGACY_DATA_DIR,
    ),
    "30": FirebirdImage(
        key="30",
        image=_env_image("ODIN_FIREBIRD_30_IMAGE", "firebirdsql/firebird:3.0.9"),
        major=3,
        bin_dir=MODERN_BIN_DIR,
        data_dir=MODERN_DATA_DIR,
    ),
    "40": FirebirdImage(
        key="40",
        image=_env_image("ODIN_FIREBIRD_40_IMAGE", "firebirdsql/firebird:4.0.5"),
        major=4,
        bin_dir=MODERN_BIN_DIR,
        data_dir=MODERN_DATA_DIR,
    ),
    "50": FirebirdImage(
        key="50",
        image=_env_image("ODIN_FIREBIRD_50_IMAGE", "firebirdsql/firebird:latest"),
        major=5,
        bin_dir=MODERN_BIN_DIR,
        data_dir=MODERN_DATA_DIR,
    ),
    "60": FirebirdImage(
        key="60",
        image=_env_image("ODIN_FIREBIRD_60_IMAGE", "firebirdsql/firebird:6-snapshot"),
        major=6,
        bin_dir=MODERN_BIN_DIR,
        data_dir=MODERN_DATA_DIR,
    ),
}


def _last_value(output: str) -> str:
    """Última línea con contenido útil de la salida tabular de ``isql``."""
    for line in reversed(output.splitlines()):
        stripped = line.strip()
        if stripped and set(stripped) - set("=- "):
            return stripped
    raise FirebirdContainerError(f"salida de isql vacía o ilegible: {output!r}")


class FirebirdContainer:
    """Contenedor Docker de Firebird con la base creada por la imagen."""

    def __init__(
        self,
        image: FirebirdImage | str,
        *,
        name: str | None = None,
        mount: Path | None = None,
        root_password: str = DEFAULT_ROOT_PASSWORD,
        database_name: str | None = DEFAULT_DATABASE_NAME,
        user: str | None = None,
        user_password: str | None = None,
        charset: str | None = None,
    ) -> None:
        self.image = modern_image(image) if isinstance(image, str) else image
        self.name = name or f"odin-firebird-{self.image.key}-{uuid.uuid4().hex[:8]}"
        self.mount = None if mount is None else Path(mount)
        self.root_password = root_password
        self.database_name = database_name
        self.user = user
        self.user_password = user_password
        self.charset = charset

    def __enter__(self) -> FirebirdContainer:
        self.start()
        self.wait_ready()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.remove()

    def start(self, *, timeout: float = 300.0) -> None:
        """Arranca el contenedor con puerto publicado dinámico (``-P``)."""
        self.remove()
        completed = subprocess.run(
            self._run_command(), capture_output=True, text=True, timeout=timeout
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise FirebirdContainerError(f"no se pudo iniciar {self.image.image}: {detail}")

    def remove(self) -> None:
        """Elimina el contenedor si existe (idempotente)."""
        if DOCKER is None:
            return
        subprocess.run([DOCKER, "rm", "-f", self.name], capture_output=True, text=True)

    def _run_command(self) -> list[str]:
        if DOCKER is None:
            raise FirebirdContainerError("Docker no está instalado en el host")
        command = [DOCKER, "run", "--name", self.name, "-d", "-P"]
        for key, value in self._environment().items():
            command += ["-e", f"{key}={value}"]
        if self.mount is not None:
            command += ["-v", f"{self.mount}:{self.mount}"]
        command.append(self.image.image)
        return command

    def _environment(self) -> dict[str, str]:
        return self.image.environment(
            root_password=self.root_password,
            database_name=self.database_name,
            user=self.user,
            user_password=self.user_password,
            charset=self.charset,
        )

    @property
    def port(self) -> int:
        """Puerto del host mapeado al 3050 del contenedor."""
        if DOCKER is None:
            raise FirebirdContainerError("Docker no está instalado en el host")
        completed = subprocess.run(
            [DOCKER, "port", self.name, "3050/tcp"], capture_output=True, text=True
        )
        mapped = completed.stdout.strip().splitlines()
        if completed.returncode != 0 or not mapped:
            raise FirebirdContainerError(f"Docker no publicó el puerto 3050 de {self.name}")
        return int(mapped[0].rsplit(":", 1)[1])

    def database_spec(self, name: str | None = None) -> str:
        """Conexión ``localhost/3050:<ruta>`` desde dentro del contenedor."""
        return self.image.database_spec(name or self.database_name or DEFAULT_DATABASE_NAME)

    def exec(
        self,
        args: Sequence[str],
        *,
        input_text: str | None = None,
        user: str | None = None,
        timeout: float = 60.0,
    ) -> subprocess.CompletedProcess[str]:
        """Ejecuta un comando dentro del contenedor (falla con su stderr)."""
        if DOCKER is None:
            raise FirebirdContainerError("Docker no está instalado en el host")
        command = [DOCKER, "exec"]
        if user is not None:
            command += ["--user", user]
        if input_text is not None:
            command.append("-i")
        command += [self.name, *args]
        completed = subprocess.run(
            command, capture_output=True, text=True, input=input_text, timeout=timeout
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise FirebirdContainerError(
                f"'{' '.join(args)}' falló en el contenedor "
                f"(código {completed.returncode}): {detail}"
            )
        return completed

    def wait_ready(
        self, *, timeout: float = DEFAULT_READY_TIMEOUT_SEC, interval: float = 2.0
    ) -> None:
        """Espera a que el servidor acepte consultas (reintentos con ``isql``).

        No basta el código de salida de ``isql``: Firebird 3.0 devuelve 0 ante
        un fallo de conexión, así que se exige un resultado real.
        """
        deadline = time.monotonic() + timeout
        last_error = "sin detalle"
        while True:
            try:
                if _last_value(self.isql("SELECT 1 FROM rdb$database;", timeout=15.0)) == "1":
                    return
                last_error = "isql no devolvió el valor esperado"
            except (FirebirdContainerError, subprocess.TimeoutExpired) as exc:
                last_error = str(exc)
            if time.monotonic() >= deadline:
                raise FirebirdContainerError(
                    f"Firebird no respondió en {timeout:.0f} s: {last_error}"
                )
            time.sleep(interval)

    def isql(
        self,
        sql: str,
        *,
        database: str | None = None,
        user: str | None = None,
        password: str | None = None,
        timeout: float = 60.0,
    ) -> str:
        """Ejecuta SQL con el ``isql`` de la imagen y devuelve su stdout."""
        effective_user = "SYSDBA" if user is None else user
        effective_password = self.root_password if password is None else password
        spec = self.database_spec() if database is None else database
        completed = self.exec(
            [self.image.isql, "-user", effective_user, "-password", effective_password, spec],
            input_text=sql,
            timeout=timeout,
        )
        stderr = completed.stderr or ""
        if "Statement failed" in stderr or "-SQL error code" in stderr:
            raise FirebirdContainerError(f"isql reportó un error: {stderr.strip()}")
        return completed.stdout

    def count_rows(
        self,
        table: str,
        *,
        database: str | None = None,
        user: str | None = None,
        password: str | None = None,
        timeout: float = 60.0,
    ) -> int:
        """Cuenta las filas de ``table`` vía ``isql`` (para verificar el restore)."""
        value = _last_value(
            self.isql(
                f"SELECT COUNT(*) FROM {table};",
                database=database,
                user=user,
                password=password,
                timeout=timeout,
            )
        )
        if not value.isdigit():
            raise FirebirdContainerError(f"COUNT(*) ilegible en la salida de isql: {value!r}")
        return int(value)

    def character_set(
        self,
        *,
        database: str | None = None,
        user: str | None = None,
        password: str | None = None,
        timeout: float = 60.0,
    ) -> str:
        """Charset por defecto de la base indicada (evidencia de la variante)."""
        return _last_value(
            self.isql(
                "SELECT rdb$character_set_name FROM rdb$database;",
                database=database,
                user=user,
                password=password,
                timeout=timeout,
            )
        )

    def gbak_version(self, *, timeout: float = 30.0) -> str:
        """Versión del ``gbak`` de la imagen (evidencia de la familia).

        ``gbak -Z`` imprime la versión pero puede salir con código 1 (p. ej.
        Firebird 5 exige además nombres de archivo), así que aquí no se usa la
        validación estricta de ``exec``.
        """
        if DOCKER is None:
            raise FirebirdContainerError("Docker no está instalado en el host")
        completed = subprocess.run(
            [DOCKER, "exec", "--user", "root", self.name, self.image.gbak, "-Z"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = f"{completed.stdout}\n{completed.stderr}"
        for line in output.splitlines():
            if "version" in line.lower():
                return line.strip()
        return output.strip()

    def gbak(self, args: Sequence[str], *, timeout: float = 120.0) -> str:
        """Ejecuta el ``gbak`` de la imagen (misma familia que el servidor)."""
        return self.exec([self.image.gbak, *args], user="root", timeout=timeout).stdout

    def gbak_wrapper(self, path: Path) -> Path:
        """Escribe un ejecutable que reenvía sus argumentos al ``gbak`` de la imagen.

        Es el ``gbak_path`` que se pasa a ``BackupExecutor``: los argumentos
        (cadena de conexión y rutas) se construyen para que sean válidos
        *dentro* del contenedor, con ``mount`` visible en la misma ruta
        absoluta. En Windows se escribe un ``.cmd`` equivalente.
        """
        if sys.platform == "win32":
            target = path.with_suffix(".cmd")
            content = f"@docker exec --user root {self.name} {self.image.gbak} %*\r\n"
        else:
            target = path
            content = (
                f'#!/bin/sh\nexec docker exec --user root {self.name} '
                f'{self.image.gbak} "$@"\n'
            )
        target.write_text(content, encoding="utf-8", newline="")
        if sys.platform != "win32":
            target.chmod(0o755)
        return target
