"""Modo servicio de ODIN: contrato portable y gestores por plataforma (Item 059).

Re-exporta la API pública de ``odin.service.base`` (definición, estado,
errores y despacho). Los gestores concretos ``odin.service.linux`` (systemd) y
``odin.service.windows`` (pywin32) **no** se importan acá: ``create_service_manager``
los resuelve en forma diferida para que importar este paquete en Linux no toque
pywin32.
"""

from odin.service.base import (
    DEFAULT_DESCRIPTION,
    DEFAULT_DISPLAY_NAME,
    DEFAULT_RESTART_DELAY_SECONDS,
    SERVICE_NAME,
    ServiceError,
    ServiceManager,
    ServiceManagerKind,
    ServiceNotInstalledError,
    ServiceRuntime,
    ServiceSpec,
    ServiceStatus,
    ServiceUnsupportedError,
    create_service_manager,
    ensure_absolute_config_path,
)

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
