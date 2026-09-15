"""Contrato portable del modo servicio de ODIN (Item 059).

El modo residente (Etapa 7) comparte una interfaz independiente del SO que
consumen los gestores concretos (``odin.service.linux`` sobre systemd,
``odin.service.windows`` sobre pywin32), la CLI (``odin service
install|uninstall|start|stop|status``) y el runner compartido del scheduler
(Item 065).

Contenido:

- ``ServiceSpec``: definición inmutable del servicio a instalar —nombre,
  display name, descripción, ``config_path`` **absoluta y validada** (el
  servicio corre desatendido: no puede depender del cwd ni de ``ODIN_CONFIG``),
  ``executable`` con el argv derivado (``service run --config <ruta>``),
  ``working_dir``, ``auto_start``, ``restart_on_failure``,
  ``restart_delay_seconds`` y ``account`` (``None`` = cuenta por defecto de la
  plataforma).
- ``ServiceStatus``: fotografía del servicio (instalado, corriendo,
  arranque automático, política de reinicio, gestor y detalle). Un servicio no
  instalado es un estado válido (``installed=False``), no un error.
- ``ServiceManager`` (ABC): ``install(spec)``, ``uninstall()``, ``start()``,
  ``stop()`` y ``status()``; las operaciones de ciclo de vida devuelven el
  mensaje listo para imprimir en la CLI.
- ``ServiceRuntime`` (Protocol): contrato ``run()``/``stop()`` que el runner
  del Item 065 implementará y que el ``SvcDoRun``/``SvcStop`` de Windows
  consume.
- ``create_service_manager``: despacho por plataforma con **import diferido**
  (importar ``odin.service`` en Linux no toca pywin32) y error claro fuera de
  Linux/Windows.

Los errores se agrupan bajo ``ServiceError``: ``ServiceUnsupportedError``
(plataforma o soporte faltante) y ``ServiceNotInstalledError`` (la operación
requiere un servicio instalado).
"""

from __future__ import annotations

import importlib
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar, Protocol, cast

__all__ = [
    "DEFAULT_DESCRIPTION",
    "DEFAULT_DISPLAY_NAME",
    "DEFAULT_RESTART_DELAY_SECONDS",
    "SERVICE_NAME",
    "ServiceError",
    "ServiceManager",
    "ServiceManagerKind",
    "ServiceNotInstalledError",
    "ServiceRuntime",
    "ServiceSpec",
    "ServiceStatus",
    "ServiceUnsupportedError",
    "create_service_manager",
    "ensure_absolute_config_path",
]

SERVICE_NAME = "odin"
DEFAULT_DISPLAY_NAME = "ODIN Backup Service"
DEFAULT_DESCRIPTION = (
    "Respaldo externo de bases de datos Firebird (gbak + 7z + SFTP + correo) "
    "disparado por el scheduler interno."
)
DEFAULT_RESTART_DELAY_SECONDS = 5


class ServiceError(RuntimeError):
    """Error operativo del modo servicio (instalación, control o consulta)."""


class ServiceUnsupportedError(ServiceError):
    """La plataforma no soporta el modo servicio o le falta el soporte requerido."""


class ServiceNotInstalledError(ServiceError):
    """La operación requiere un servicio instalado y no lo está."""


class ServiceManagerKind(StrEnum):
    """Gestor de servicios de la plataforma (``systemd``/``windows``)."""

    SYSTEMD = "systemd"
    WINDOWS = "windows"


def ensure_absolute_config_path(config_path: Path | str) -> Path:
    """Devuelve ``config_path`` como ``Path`` absoluta o lanza ``ServiceError``.

    El modo servicio se instala para correr desatendido (systemd/SCM): la ruta
    del JSON no puede resolverse contra el cwd del proceso ni contra
    ``ODIN_CONFIG``, así que se exige una ruta absoluta en el momento de
    construir el ``ServiceSpec``.
    """
    path = Path(config_path)
    if not path.is_absolute():
        raise ServiceError(
            "la ruta de configuración del servicio debe ser absoluta (el servicio "
            f"corre desatendido y no depende del cwd): {path}"
        )
    return path


@dataclass(frozen=True, slots=True)
class ServiceSpec:
    """Definición del servicio residente a instalar.

    ``config_path`` debe ser absoluta (``ensure_absolute_config_path``);
    ``working_dir`` es opcional y, si se omite, se usa el directorio del JSON
    (``resolved_working_dir``). ``argv`` deriva la línea de comando con la que
    los gestores arrancan el servicio —``<executable> service run --config
    <ruta>``—, sin depender de variables de entorno.
    """

    config_path: Path
    executable: str = "odin"
    working_dir: Path | None = None
    name: str = SERVICE_NAME
    display_name: str = DEFAULT_DISPLAY_NAME
    description: str = DEFAULT_DESCRIPTION
    auto_start: bool = True
    restart_on_failure: bool = True
    restart_delay_seconds: int = DEFAULT_RESTART_DELAY_SECONDS
    account: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "config_path", ensure_absolute_config_path(self.config_path))
        if self.working_dir is not None:
            object.__setattr__(
                self, "working_dir", ensure_absolute_config_path(self.working_dir)
            )
        if not self.executable.strip():
            raise ServiceError("el ejecutable del servicio no puede estar vacío")
        if not self.name.strip() or any(char.isspace() for char in self.name):
            raise ServiceError(f"nombre de servicio inválido: {self.name!r}")
        if self.restart_delay_seconds < 0:
            raise ServiceError(
                "restart_delay_seconds no puede ser negativo: "
                f"{self.restart_delay_seconds}"
            )

    @property
    def resolved_working_dir(self) -> Path:
        """Directorio de trabajo efectivo (el del JSON si no se indicó otro)."""
        return self.working_dir if self.working_dir is not None else self.config_path.parent

    @property
    def arguments(self) -> tuple[str, ...]:
        """Argumentos con los que se ejecuta el scheduler en modo servicio."""
        return ("service", "run", "--config", str(self.config_path))

    @property
    def argv(self) -> tuple[str, ...]:
        """Línea de comando completa (ejecutable + argumentos)."""
        return (self.executable, *self.arguments)


@dataclass(frozen=True, slots=True)
class ServiceStatus:
    """Estado consultable del servicio en el gestor de la plataforma.

    ``installed=False`` describe un servicio no instalado (no es un error);
    ``auto_start``, ``restart_on_failure``, ``manager`` y ``detail`` quedan en
    ``None`` cuando no aplican o el gestor no los informa.
    """

    installed: bool
    running: bool = False
    auto_start: bool | None = None
    restart_on_failure: bool | None = None
    manager: ServiceManagerKind | None = None
    detail: str | None = None

    @classmethod
    def not_installed(
        cls, manager: ServiceManagerKind, detail: str | None = None
    ) -> ServiceStatus:
        """Estado canónico de un servicio no instalado."""
        return cls(installed=False, manager=manager, detail=detail)


class ServiceManager(ABC):
    """Ciclo de vida del servicio residente en el gestor de la plataforma.

    Cada operación devuelve el mensaje a imprimir (instalación, guía sin
    permisos, arranque, parada) o lanza ``ServiceError``. ``status()`` nunca
    falla por un servicio ausente: devuelve ``ServiceStatus(installed=False)``.
    """

    manager: ClassVar[ServiceManagerKind]

    @abstractmethod
    def install(self, spec: ServiceSpec) -> str:
        """Instala (o reemplaza) el servicio descrito por ``spec``."""

    @abstractmethod
    def uninstall(self) -> str:
        """Desinstala el servicio; es idempotente."""

    @abstractmethod
    def start(self) -> str:
        """Arranca el servicio y espera su transición a "en ejecución"."""

    @abstractmethod
    def stop(self) -> str:
        """Detiene el servicio y espera su transición a "detenido"."""

    @abstractmethod
    def status(self) -> ServiceStatus:
        """Consulta el estado del servicio (no instalado incluido)."""


class ServiceRuntime(Protocol):
    """Runtime del scheduler que los gestores arrancan y detienen.

    El runner compartido (Item 065) lo implementa: ``run()`` bloquea hasta que
    el servicio se detiene y devuelve el exit code; ``stop()`` es thread-safe e
    idempotente y lo invocan el ``SvcStop`` de Windows o la señal de systemd.
    """

    def run(self) -> int: ...

    def stop(self) -> None: ...


def _load_manager(
    module_name: str, class_name: str, config_path: Path | str, kwargs: dict[str, Any]
) -> ServiceManager:
    """Importa el gestor concreto de ``module_name`` y lo construye.

    El import es diferido por diseño: importar este módulo en Linux no debe
    tocar pywin32 ni exigir systemd, y construir el gestor de Windows tampoco
    (pywin32 se importa dentro de cada operación). El módulo debe exponer
    ``class_name``; si no, es un error de instalación del paquete.
    """
    module = importlib.import_module(module_name)
    manager_class = getattr(module, class_name, None)
    if manager_class is None:
        raise ServiceUnsupportedError(
            f"el gestor de servicios {module_name!r} no expone {class_name}"
        )
    return cast(ServiceManager, manager_class(config_path, **kwargs))


def create_service_manager(
    config_path: Path | str,
    *,
    platform: str | None = None,
    **kwargs: Any,
) -> ServiceManager:
    """Crea el gestor de servicios de ``platform`` (``sys.platform`` por defecto).

    Los gestores concretos se importan en forma diferida: importar
    ``odin.service`` en Linux no toca pywin32 y construir el gestor de Windows
    tampoco. Una plataforma fuera de Linux/Windows lanza
    ``ServiceUnsupportedError``.
    """
    target = platform if platform is not None else sys.platform
    if target.startswith("linux"):
        return _load_manager("odin.service.linux", "LinuxServiceManager", config_path, kwargs)
    if target == "win32":
        return _load_manager("odin.service.windows", "WindowsServiceManager", config_path, kwargs)
    raise ServiceUnsupportedError(
        f"plataforma no soportada por el modo servicio de ODIN: {target!r}; "
        "se soportan Linux (systemd) y Windows Server (pywin32)."
    )
