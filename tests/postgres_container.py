"""Helper de contenedor PostgreSQL para los tests de integración (ticket 05).

Arranca un contenedor de la imagen oficial ``postgres:18`` y expone lo
necesario para un flujo de respaldo real **sin requerir ``pg_dump`` en el
host**: el binario que se usa es el de la propia imagen, invocado con
``docker exec`` a través de un wrapper (``PostgresContainer.pg_dump_wrapper``).
El ``work_dir`` se monta en la misma ruta absoluta host↔contenedor para que
las rutas que ``BackupExecutor`` pasa al wrapper sean válidas en ambos lados.

Espejo de ``tests.firebird_container.py`` (Item 069): mismo estilo, manejo de
errores (excepción única ``PostgresContainerError``) y detección de Docker
(``shutil.which``); sin matriz de imágenes —una sola imagen con override— y
con el readiness resuelto con ``pg_isready`` (cuyo código de salida sí es
confiable, a diferencia de ``isql``).

Convenciones de la imagen oficial:

- ``POSTGRES_PASSWORD`` (superusuario ``postgres``) y ``POSTGRES_DB`` (crea
  la base de trabajo con ese nombre).
- ``pg_isready``/``pg_dump`` están en el ``PATH`` de la imagen (patrón
  documentado por la propia imagen oficial: ``docker exec <nombre> psql -U
  postgres``), así que se invocan por nombre, válido también si
  ``ODIN_POSTGRES_IMAGE`` apunta a otra variante de la imagen.
- El ``pg_hba.conf`` generado por la imagen confía en ``127.0.0.1`` y en el
  socket local (auth ``trust``), así que el respaldo desde dentro del
  contenedor no pide contraseña; aun así el wrapper reenvía ``PGPASSWORD`` del
  entorno al ``docker exec`` para conservar el seam de §2.2 si el destino la
  exigiera.

Variables de entorno (opcionales):

- ``ODIN_POSTGRES_IMAGE``: imagen a usar (por defecto ``postgres:18``).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import uuid
from collections.abc import Sequence
from pathlib import Path

DOCKER = shutil.which("docker")

DEFAULT_PASSWORD = "odin-postgres"
DEFAULT_DATABASE_NAME = "odin_postgres_integration"
DEFAULT_READY_TIMEOUT_SEC = 60.0


class PostgresContainerError(RuntimeError):
    """Fallo al preparar o ejercitar un contenedor PostgreSQL de integración."""


def _env_image(variable: str, default: str) -> str:
    return os.environ.get(variable) or default


def default_image() -> str:
    """Imagen oficial ``postgres:18``, con override ``ODIN_POSTGRES_IMAGE``."""
    return _env_image("ODIN_POSTGRES_IMAGE", "postgres:18")


class PostgresContainer:
    """Contenedor Docker de PostgreSQL listo para respaldar con ``pg_dump``."""

    def __init__(
        self,
        image: str | None = None,
        *,
        name: str | None = None,
        mount: Path | None = None,
        password: str = DEFAULT_PASSWORD,
        database_name: str | None = DEFAULT_DATABASE_NAME,
        user: str = "postgres",
    ) -> None:
        self.image = image or default_image()
        self.name = name or f"odin-postgres-{uuid.uuid4().hex[:8]}"
        self.mount = None if mount is None else Path(mount)
        self.password = password
        self.database_name = database_name
        self.user = user

    def __enter__(self) -> PostgresContainer:
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
            raise PostgresContainerError(f"no se pudo iniciar {self.image}: {detail}")

    def remove(self) -> None:
        """Elimina el contenedor si existe (idempotente)."""
        if DOCKER is None:
            return
        subprocess.run([DOCKER, "rm", "-f", self.name], capture_output=True, text=True)

    def _run_command(self) -> list[str]:
        if DOCKER is None:
            raise PostgresContainerError("Docker no está instalado en el host")
        command = [DOCKER, "run", "--name", self.name, "-d", "-P"]
        for key, value in self._environment().items():
            command += ["-e", f"{key}={value}"]
        if self.mount is not None:
            command += ["-v", f"{self.mount}:{self.mount}"]
        command.append(self.image)
        return command

    def _environment(self) -> dict[str, str]:
        environment = {"POSTGRES_PASSWORD": self.password}
        if self.database_name is not None:
            environment["POSTGRES_DB"] = self.database_name
        return environment

    @property
    def port(self) -> int:
        """Puerto del host mapeado al 5432 del contenedor."""
        if DOCKER is None:
            raise PostgresContainerError("Docker no está instalado en el host")
        completed = subprocess.run(
            [DOCKER, "port", self.name, "5432/tcp"], capture_output=True, text=True
        )
        mapped = completed.stdout.strip().splitlines()
        if completed.returncode != 0 or not mapped:
            raise PostgresContainerError(f"Docker no publicó el puerto 5432 de {self.name}")
        return int(mapped[0].rsplit(":", 1)[1])

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
            raise PostgresContainerError("Docker no está instalado en el host")
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
            raise PostgresContainerError(
                f"'{' '.join(args)}' falló en el contenedor "
                f"(código {completed.returncode}): {detail}"
            )
        return completed

    def wait_ready(
        self, *, timeout: float = DEFAULT_READY_TIMEOUT_SEC, interval: float = 2.0
    ) -> None:
        """Espera a que el servidor acepte conexiones (reintentos con ``pg_isready``).

        ``pg_isready`` devuelve 0 cuando el servidor acepta conexiones y
        códigos 1/2/3 ante rechazo, falta de respuesta o argumentos inválidos,
        así que basta el código de salida vía ``exec`` (a diferencia de
        Firebird, donde ``isql`` puede devolver 0 ante un fallo de conexión).
        """
        deadline = time.monotonic() + timeout
        last_error = "sin detalle"
        while True:
            try:
                self.exec(self._isready_command(), timeout=15.0)
                return
            except (PostgresContainerError, subprocess.TimeoutExpired) as exc:
                last_error = str(exc)
            if time.monotonic() >= deadline:
                raise PostgresContainerError(
                    f"PostgreSQL no respondió en {timeout:.0f} s: {last_error}"
                )
            time.sleep(interval)

    def _isready_command(self) -> list[str]:
        """Chequeo de readiness por TCP ``127.0.0.1:5432`` (auth ``trust``).

        El socket local no sirve: durante la inicialización el entrypoint
        levanta un servidor temporal que escucha **solo** el socket
        (``listen_addresses=''``) y ``pg_isready`` lo daría por listo aunque
        el respaldo por TCP (``--host 127.0.0.1``) aún reciba
        *Connection refused*.
        """
        command = ["pg_isready", "-h", "127.0.0.1", "-p", "5432", "-U", self.user]
        if self.database_name is not None:
            command += ["-d", self.database_name]
        return command

    def pg_dump_version(self, *, timeout: float = 30.0) -> str:
        """Versión del ``pg_dump`` de la imagen (evidencia del major 18+)."""
        return self.exec(["pg_dump", "--version"], user="root", timeout=timeout).stdout.strip()

    def pg_dump_wrapper(self, path: Path) -> Path:
        """Escribe un ejecutable que reenvía sus argumentos al ``pg_dump`` de la imagen.

        Es el ``pg_dump_path`` que se pasa a ``BackupExecutor``: los argumentos
        (``--host 127.0.0.1 --port 5432`` y la ruta del ``.dump``) se
        construyen para que sean válidos *dentro* del contenedor, con
        ``mount`` visible en la misma ruta absoluta. ``PGPASSWORD`` se reenvía
        al ``docker exec`` para conservar el seam de §2.2 a través del wrapper.
        En Windows se escribe un ``.cmd`` equivalente.
        """
        if sys.platform == "win32":
            target = path.with_suffix(".cmd")
            content = (
                f"@docker exec -e PGPASSWORD=%PGPASSWORD% --user root {self.name} "
                f"pg_dump %*\r\n"
            )
        else:
            target = path
            content = (
                f'#!/bin/sh\nexec docker exec -e PGPASSWORD="$PGPASSWORD" '
                f'--user root {self.name} pg_dump "$@"\n'
            )
        target.write_text(content, encoding="utf-8", newline="")
        if sys.platform != "win32":
            target.chmod(0o755)
        return target
